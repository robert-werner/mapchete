from aiohttp import BasicAuth
import click
import fiona
import fsspec
import json
import logging
import os
from shapely.geometry import box, shape
from shapely.ops import unary_union
from tilematrix import TilePyramid
import tqdm

from mapchete.cli import utils

logger = logging.getLogger(__name__)


@click.command(help="Copy TileDirectory.")
@utils.arg_input
@utils.arg_output
@utils.opt_zoom
@utils.opt_bounds
@utils.opt_point
@utils.opt_wkt_geometry
@utils.opt_aoi
@utils.opt_overwrite
@utils.opt_verbose
@utils.opt_no_pbar
@utils.opt_debug
@utils.opt_logfile
@click.option(
    "--username", "-u",
    type=click.STRING,
    help="Username for HTTP Auth."
)
@click.option(
    "--password", "-p",
    type=click.STRING,
    help="Password for HTTP Auth."
)
def cp(
    input_,
    output,
    zoom=None,
    bounds=None,
    point=None,
    wkt_geometry=None,
    aoi=None,
    overwrite=False,
    verbose=False,
    no_pbar=False,
    debug=False,
    logfile=None,
    username=None,
    password=None
):
    """Copy TileDirectory."""
    protocol, _, host = input_.split("/")[:3]
    src_fs = fs_from_path(input_, username=username, password=password)
    dst_fs = fs_from_path(output, username=username, password=password)

    # read source TileDirectory metadata
    with src_fs.open(os.path.join(input_, "metadata.json")) as src:
        metadata = json.loads(src.read())
        tp = TilePyramid.from_dict(
            {
                k: v for k, v in metadata.get("pyramid").items()
                if k in ["grid", "tile_size", "metatiling"]
            }
        )

    # get aoi
    if aoi:
        with fiona.open(aoi) as src:
            aoi_geom = unary_union([shape(f["geometry"]) for f in src])
    elif bounds:
        aoi_geom = box(*bounds)
    else:
        aoi_geom = box(*tp.bounds)

    # copy metadata to destination if necessary
    _copy(
        src_fs,
        os.path.join(input_, "metadata.json"),
        dst_fs,
        os.path.join(output, "metadata.json")
    )

    for z in range(min(zoom), max(zoom) + 1):
        click.echo(f"copy zoom {z}...")
        for tile in tqdm.tqdm(
            list(tp.tiles_from_geom(aoi_geom, z)),
            unit="tile",
            disable=debug or no_pbar
        ):
            _copy(
                src_fs,
                os.path.join(input_, _get_tile_path(tile)),
                dst_fs,
                os.path.join(output, _get_tile_path(tile))
            )


def _copy(src_fs, src_path, dst_fs, dst_path, overwrite=False):
    if dst_fs.exists(dst_path) and not overwrite:
        return
    elif not src_fs.exists(src_path):
        return

    dst_fs.mkdir(os.path.dirname(dst_path), create_parents=True)
    if src_fs == dst_fs:
        src_fs.copy(src_path, dst_path)
    else:
        with src_fs.open(src_path, "rb") as src:
            with dst_fs.open(dst_path, "wb") as dst:
                dst.write(src.read())


def fs_from_path(path, timeout=5, session=None, username=None, password=None, **kwargs):
    """Guess fsspec FileSystem from path."""
    if path.startswith("s3://"):
        return fsspec.filesystem(
            "s3",
            requester_pays=os.environ.get("AWS_REQUEST_PAYER") == "requester",
            config_kwargs=dict(connect_timeout=timeout, read_timeout=timeout),
            session=session
        )
    elif path.startswith(("http://", "https://")):
        return fsspec.filesystem(
            "https",
            auth=BasicAuth(username, password)
        )
    else:
        return fsspec.filesystem(
            "file",
        )


def _get_tile_path(tile, basepath=None):
    return f"{tile.zoom}/{tile.row}/{tile.col}.tif"
