#!/usr/bin/env python

import rasterio
from rasterio.warp import *
import numpy as np

from tilematrix import *

def read_raster_window(input_file,
    tilematrix,
    tileindex,
    pixelbuffer=None,
    tilify=True):

    zoom, col, row = tileindex

    assert (isinstance(tilematrix, TileMatrix) or
        isinstance(tilematrix, MetaTileMatrix))

    # read source metadata
    with rasterio.open(input_file) as source:
        tl = [source.bounds.left, source.bounds.top]
        tr = [source.bounds.right, source.bounds.top]
        br = [source.bounds.right, source.bounds.bottom]
        bl = [source.bounds.left, source.bounds.bottom]
        source_envelope = Polygon([tl, tr, br, bl])
        source_crs = source.crs
        source_affine = source.affine
        source_meta = source.meta
        source_shape = source.shape
        source_nodata = int(source.nodatavals[0])

    # compute target metadata and initiate numpy array
    tile_geom = tilematrix.tile_bbox(zoom, col, row, pixelbuffer)

    try:
        assert tile_geom.intersects(source_envelope)

        left, bottom, right, top = tilematrix.tile_bounds(zoom, col, row,
            pixelbuffer)
        pixelsize = tilematrix.pixelsize(zoom)
        if pixelbuffer:
            destination_pixel = tilematrix.px_per_tile + (pixelbuffer * 2)
        else:
            destination_pixel = tilematrix.px_per_tile
        destination_shape = (destination_pixel, destination_pixel)
        destination_crs = tilematrix.crs
        width, height = destination_shape
        destination_data = np.zeros(destination_shape, np.int16)
    
        # compute target window
        out_left, out_bottom, out_right, out_top = transform_bounds(
            source_crs, destination_crs, left, bottom, right, top, densify_pts=21)
    
        # compute target affine
        destination_affine = calculate_default_transform(
            source_crs,
            destination_crs,
            width,
            height,
            out_left,
            out_bottom,
            out_right,
            out_top,
            resolution=(pixelsize, pixelsize))[0]

        # open window with rasterio
        with rasterio.open(input_file) as source:
            minrow, mincol = source.index(out_left, out_top)
            maxrow, maxcol = source.index(out_right, out_bottom)
            window_offset_row = minrow
            window_offset_col = mincol
            minrow, minrow_offset = clean_pixel_coordinates(minrow, source_shape[0])
            maxrow, maxrow_offset = clean_pixel_coordinates(maxrow, source_shape[0])
            mincol, mincol_offset = clean_pixel_coordinates(mincol, source_shape[1])
            maxcol, maxcol_offset = clean_pixel_coordinates(maxcol, source_shape[1])
            rows = (minrow, maxrow)
            cols = (mincol, maxcol)

            window_data = source.read(1, window=(rows, cols))
            if minrow_offset:
                nullarray = np.empty((minrow_offset, window_data.shape[1]), dtype="int16")
                nullarray[:] = source_nodata
                newarray = np.concatenate((nullarray, window_data), axis=0)
                window_data = newarray
            if maxrow_offset:
                nullarray = np.empty((maxrow_offset, window_data.shape[1]), dtype="int16")
                nullarray[:] = source_nodata
                newarray = np.concatenate((window_data, nullarray), axis=0)
                window_data = newarray
            if mincol_offset:
                nullarray = np.empty((window_data.shape[0], mincol_offset), dtype="int16")
                nullarray[:] = source_nodata
                newarray = np.concatenate((nullarray, window_data), axis=1)
                window_data = newarray
            if maxcol_offset:
                nullarray = np.empty((window_data.shape[0], maxcol_offset), dtype="int16")
                nullarray[:] = source_nodata
                newarray = np.concatenate((window_data, nullarray), axis=1)
                window_data = newarray

            window_vector_affine = source_affine.translation(window_offset_col, window_offset_row)
            window_affine = source_affine * window_vector_affine

            window_meta = source_meta
            window_meta['transform'] = window_affine
            window_meta['height'] = window_data.shape[0]
            window_meta['width'] = window_data.shape[1]
            window_meta['compress'] = "lzw"

            tile_metadata = window_meta
            tile_data = window_data

        # if tilify, reproject/resample
        if tilify:
            destination_meta = source_meta
            destination_meta['transform'] = destination_affine
            destination_meta['height'] = height
            destination_meta['width'] = width
            destination_meta['compress'] = "lzw"
            try:
                reproject(
                    window_data,
                    destination_data,
                    src_transform=window_affine,
                    src_crs=source_crs,
                    src_nodata=source_nodata,
                    dst_transform=destination_affine,
                    dst_crs=destination_crs,
                    dst_nodata=source_nodata,
                    resampling=RESAMPLING.lanczos)
            except:
                destination_data = None
                destination_meta = None
                raise
            tile_metadata = destination_meta
            tile_data = destination_data
    except:        
        tile_metadata, tile_data = None, None

    # return tile metadata and data (numpy)
    return tile_metadata, tile_data


def write_raster_window(output_file,
    tilematrix,
    tileindex,
    metadata,
    rasterdata,
    pixelbuffer=0):

    zoom, col, row = tileindex

    # get write window bounds (i.e. tile bounds plus pixelbuffer) in affine
    out_left, out_bottom, out_right, out_top = tilematrix.tile_bounds(zoom,
        col, row, pixelbuffer)
    out_width = tilematrix.px_per_tile + (pixelbuffer * 2)
    out_height = tilematrix.px_per_tile + (pixelbuffer * 2)
    pixelsize = tilematrix.pixelsize(zoom)
    destination_affine = calculate_default_transform(
        tilematrix.crs,
        tilematrix.crs,
        out_width,
        out_height,
        out_left,
        out_bottom,
        out_right,
        out_top,
        resolution=(pixelsize, pixelsize))[0]

    # convert to pixel coordinates
    input_left = metadata["transform"][2]
    input_top = metadata["transform"][5]
    input_bottom = input_top + metadata["height"] * metadata["transform"][4]
    input_right = input_left + metadata["width"] * metadata["transform"][0]
    ul = input_left, input_top
    ur = input_right, input_top
    lr = input_right, input_bottom
    ll = input_left, input_bottom
    px_left = int(round((out_left - input_left) / pixelsize))
    px_bottom = int(round((out_bottom - input_top) / -pixelsize))
    px_right = int(round((input_left - out_right) / -pixelsize))
    px_top = int(round((input_top - out_top) / pixelsize))
    window = (px_top, px_bottom), (px_left, px_right)

    # fill with nodata if necessary
    # TODO
    dst_data = rasterdata[px_top:px_bottom,px_left:px_right]

    # write to output file
    dst_metadata = metadata
    dst_metadata["width"] = out_width
    dst_metadata["height"] = out_height
    dst_metadata["transform"] = destination_affine
    with rasterio.open(output_file, 'w', **dst_metadata) as dst:
        dst.write_band(1, dst_data)


def read_vector_window(input_file,
    tilematrix,
    tileindex,
    pixelbuffer=None,
    tilify=True):

    zoom, col, row = tileindex

    assert (isinstance(tilematrix, TileMatrix) or
        isinstance(tilematrix, MetaTileMatrix))

    # read source metadata

    # compute target metadata

    # compute target window

    # open with fiona

    # if tilify, reproject/resample

    # return source metadata and data (shapely)


# auxiliary

def clean_pixel_coordinates(coordinate, maximum):
    # Crops pixel coordinate to 0 or maximum (array.shape) if necessary
    # and returns an offset if necessary.
    offset = None
    if coordinate < 0:
        offset = -coordinate
        coordinate = 0
    if coordinate > maximum:
        offset = coordinate - maximum
        coordinate = maximum
    return coordinate, offset
