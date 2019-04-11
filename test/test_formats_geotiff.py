"""Test GeoTIFF as process output."""

import numpy as np
import numpy.ma as ma
import os
import rasterio
from rasterio.io import MemoryFile
import shutil
from tilematrix import Bounds

import mapchete
from mapchete.formats.default import gtiff
from mapchete.tile import BufferedTilePyramid


def test_output_data(mp_tmpdir):
    """Check GeoTIFF as output data."""
    output_params = dict(
        grid="geodetic",
        format="GeoTIFF",
        path=mp_tmpdir,
        pixelbuffer=0,
        metatiling=1,
        bands=1,
        dtype="int16",
        delimiters=dict(
            bounds=Bounds(-180.0, -90.0, 180.0, 90.0),
            effective_bounds=Bounds(-180.439453125, -90.0, 180.439453125, 90.0),
            zoom=[5],
            process_bounds=Bounds(-180.0, -90.0, 180.0, 90.0)
        )
    )
    output = gtiff.OutputData(output_params)
    assert output.path == mp_tmpdir
    assert output.file_extension == ".tif"
    tp = BufferedTilePyramid("geodetic")
    tile = tp.tile(5, 5, 5)
    # get_path
    assert output.get_path(tile) == os.path.join(*[
        mp_tmpdir, "5", "5", "5"+".tif"])
    # prepare_path
    try:
        temp_dir = os.path.join(*[mp_tmpdir, "5", "5"])
        output.prepare_path(tile)
        assert os.path.isdir(temp_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    # profile
    assert isinstance(output.profile(tile), dict)
    # write
    try:
        data = np.ones((1, ) + tile.shape)*128
        output.write(tile, data)
        # tiles_exist
        assert output.tiles_exist(tile)
        # read
        data = output.read(tile)
        assert isinstance(data, np.ndarray)
        assert not data[0].mask.any()
    finally:
        shutil.rmtree(mp_tmpdir, ignore_errors=True)
    # read empty
    try:
        data = output.read(tile)
        assert isinstance(data, np.ndarray)
        assert data[0].mask.all()
    finally:
        shutil.rmtree(mp_tmpdir, ignore_errors=True)
    # empty
    try:
        empty = output.empty(tile)
        assert isinstance(empty, ma.MaskedArray)
        assert not empty.any()
    finally:
        shutil.rmtree(mp_tmpdir, ignore_errors=True)
    # deflate with predictor
    try:
        output_params.update(compress="deflate", predictor=2)
        output = gtiff.OutputData(output_params)
        assert output.profile(tile)["compress"] == "deflate"
        assert output.profile(tile)["predictor"] == 2
    finally:
        shutil.rmtree(mp_tmpdir, ignore_errors=True)
    # using deprecated "compression" property
    try:
        output_params.update(compression="deflate", predictor=2)
        output = gtiff.OutputData(output_params)
        assert output.profile(tile)["compress"] == "deflate"
        assert output.profile(tile)["predictor"] == 2
    finally:
        shutil.rmtree(mp_tmpdir, ignore_errors=True)


def test_for_web(client, mp_tmpdir):
    """Send GTiff via flask."""
    tile_base_url = '/wmts_simple/1.0.0/cleantopo_br/default/WGS84/'
    for url in ["/"]:
        response = client.get(url)
        assert response.status_code == 200
    for url in [
        tile_base_url+"5/30/62.tif",
        tile_base_url+"5/30/63.tif",
        tile_base_url+"5/31/62.tif",
        tile_base_url+"5/31/63.tif",
    ]:
        response = client.get(url)
        assert response.status_code == 200
        img = response.data
        with MemoryFile(img) as memfile:
            with memfile.open() as dataset:
                assert dataset.read().any()


def test_input_data(mp_tmpdir, cleantopo_br):
    """Check GeoTIFF proces output as input data."""
    with mapchete.open(cleantopo_br.path) as mp:
        tp = BufferedTilePyramid("geodetic")
        # TODO tile with existing but empty data
        tile = tp.tile(5, 5, 5)
        output_params = dict(
            grid="geodetic",
            format="GeoTIFF",
            path=mp_tmpdir,
            pixelbuffer=0,
            metatiling=1,
            bands=2,
            dtype="int16",
            delimiters=dict(
                bounds=Bounds(-180.0, -90.0, 180.0, 90.0),
                effective_bounds=Bounds(-180.439453125, -90.0, 180.439453125, 90.0),
                zoom=[5],
                process_bounds=Bounds(-180.0, -90.0, 180.0, 90.0)
            )
        )
        output = gtiff.OutputData(output_params)
        with output.open(tile, mp, resampling="nearest") as input_tile:
            assert input_tile.resampling == "nearest"
            for data in [
                input_tile.read(), input_tile.read(1), input_tile.read([1]),
                # TODO assert valid indexes are passed input_tile.read([1, 2])
            ]:
                assert isinstance(data, ma.masked_array)
                assert input_tile.is_empty()
        # open without resampling
        with output.open(tile, mp) as input_tile:
            pass


def test_write_geotiff_tags(
    mp_tmpdir, cleantopo_br, write_rasterfile_tags_py
):
    """Pass on metadata tags from user process to rasterio."""
    conf = dict(**cleantopo_br.dict)
    conf.update(process=write_rasterfile_tags_py)
    with mapchete.open(conf) as mp:
        for tile in mp.get_process_tiles():
            data, tags = mp.execute(tile)
            assert data.any()
            assert isinstance(tags, dict)
            mp.write(process_tile=tile, data=(data, tags))
            # read data
            out_path = mp.config.output.get_path(tile)
            with rasterio.open(out_path) as src:
                assert "filewide_tag" in src.tags()
                assert src.tags()["filewide_tag"] == "value"
                assert "band_tag" in src.tags(1)
                assert src.tags(1)["band_tag"] == "True"


def test_s3_write_output_data(gtiff_s3, s3_example_tile, mp_s3_tmpdir):
    """Write and read output."""
    with mapchete.open(gtiff_s3.dict) as mp:
        process_tile = mp.config.process_pyramid.tile(*s3_example_tile)
        # basic functions
        assert mp.config.output.profile()
        assert mp.config.output.empty(process_tile).mask.all()
        assert mp.config.output.get_path(process_tile)
        # check if tile exists
        assert not mp.config.output.tiles_exist(process_tile)
        # write
        mp.batch_process(tile=process_tile.id)
        # check if tile exists
        assert mp.config.output.tiles_exist(process_tile)
        # read again, this time with data
        data = mp.config.output.read(process_tile)
        assert isinstance(data, np.ndarray)
        assert not data[0].mask.all()


def test_output_single_gtiff(output_single_gtiff_mapchete):
    zoom = 5
    with mapchete.open(output_single_gtiff_mapchete.path) as mp:
        process_tile = next(mp.get_process_tiles(zoom))
        # basic functions
        assert mp.config.output.profile()
        assert mp.config.output.empty(process_tile).mask.all()
        assert mp.config.output.get_path(process_tile)
        # check if tile exists
        assert not mp.config.output.tiles_exist(process_tile)
        # write
        mp.batch_process(tile=process_tile.id)
        # check if tile exists
        assert mp.config.output.tiles_exist(process_tile)
        # read again, this time with data
        data = mp.config.output.read(process_tile)
        assert isinstance(data, np.ndarray)
        assert not data[0].mask.all()

