from collections import namedtuple
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
import numpy as np
import gpxpy
from . import parse


GPSData = namedtuple("GPSData",
                     [
                         "description",
                         "timestamp",
                         "micros_after_start",
                         "precision",
                         "fix",
                         "latitude",
                         "longitude",
                         "altitude",
                         "speed_2d",
                         "speed_3d",
                         "units",
                         "npoints"
                     ])


def extract_gps_blocks(stream):
    """ Extract GPS data blocks from binary stream

    This is a generator on lists `KVLItem` objects. In
    the GPMF stream, GPS data comes into blocks of several
    different data items. For each of these blocks we return a list.

    Parameters
    ----------
    stream: bytes
        The raw GPMF binary stream

    Returns
    -------
    gps_items_generator: generator
        Generator of lists of `KVLItem` objects
    """
    for s in parse.filter_klv(stream, "STRM"):
        content = []
        is_gps = False
        for elt in s.value:
            
            content.append(elt)
            
            if elt.key == "GPS9":
                is_gps = True
        if is_gps:
            yield content


def parse_gps_block(gps_block):
    """Turn GPS data blocks into `GPSData` objects

    Parameters
    ----------
    gps_block: list of KVLItem
        A list of KVLItem corresponding to a GPS data block.

    Returns
    -------
    gps_data: GPSData
        A GPSData object holding the GPS information of a block. 17:52:41.24148 17:54:48.400 127.15852
    """
    block_dict = {
        s.key: s for s in gps_block
    }
    
    tempy = block_dict["GPS9"].value.T[-1]
    gpsClone = np.concatenate((block_dict["GPS9"].value, (tempy%65536)[...,None]), 1)
    
    if tempy.any() < 0:
        print("That was unexpected, the error must be real big")
        tempy += 4294967296
        
    gpsClone.T[7] = tempy//65536
    gps_data = gpsClone * 1.0 / block_dict["SCAL"].value
    latitude, longitude, altitude, speed_2d, speed_3d, days, secs, DOP, fix = gps_data.T
    return GPSData(
        description=block_dict["STNM"].value,
        timestamp=(days, secs), #Need to intagrate days and seconds to a legit timestamp
        micros_after_start = block_dict["STMP"],
        precision=DOP,
        fix=fix,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        speed_2d=speed_2d,
        speed_3d=speed_3d,
        units=block_dict["UNIT"].value,
        npoints=len(gps_data)
    )


FIX_TYPE = {
    0: "none",
    2: "2d",
    3: "3d"
}


def _make_speed_extensions(gps_data, i):
    speed_2d = ET.Element("speed_2d")
    value = ET.SubElement(speed_2d, "value")
    value.text = "%g" % gps_data.speed_2d[i]
    unit = ET.SubElement(speed_2d, "unit")
    unit.text = "m/s"

    speed_3d = ET.Element("speed_3d")
    value = ET.SubElement(speed_3d, "value")
    value.text = "%g" % gps_data.speed_3d[i]
    unit = ET.SubElement(speed_3d, "unit")
    unit.text = "m/s"

    return [speed_2d, speed_3d]


def make_pgx_segment(gps_blocks, first_only=False, speeds_as_extensions=True):
    """Convert a list of GPSData objects into a GPX track segment.

    Parameters
    ----------
    gps_blocks: list of GPSData
        A list of GPSData objects
    first_only: bool, optional (default=False)
        If True use only the first GPS entry of each data block.
    speeds_as_extensions: bool, optional (default=True)
        If True, include 2d and 3d speed values as exentensions of
        the GPX trackpoints. This is especially useful when saving
        to GPX 1.1 format.

    Returns
    -------
    gpx_segment: gpxpy.gpx.GPXTrackSegment
        A gpx track segment.
    """

    track_segment = gpxpy.gpx.GPXTrackSegment()

    for gps_data in gps_blocks:
        # Reference says the frequency is about 18 Hz and other GPS data about 1Hz
        stop = 1 if first_only else gps_data.npoints
        if(gps_data.precision[0] < 10):
            starttime = datetime(2000, 1, 1, 0, 0, 0, 0) + timedelta(days = gps_data.timestamp[0][0], seconds = gps_data.timestamp[1][0]) + timedelta(microseconds=int(gps_data.micros_after_start.value) * -1)

        for i in range(stop):
            
                
            time = datetime(2000, 1, 1, 0, 0, 0, 0) + timedelta(days = gps_data.timestamp[0][i], seconds = gps_data.timestamp[1][i])
            
            tp = gpxpy.gpx.GPXTrackPoint(
                latitude=gps_data.latitude[i],
                longitude=gps_data.longitude[i],
                elevation=gps_data.altitude[i],
                speed=gps_data.speed_3d[i],
                position_dilution=gps_data.precision[i],
                time = time,
                symbol="Square",
            )

            tp.type_of_gpx_fix = FIX_TYPE[gps_data.fix[i]]

            if speeds_as_extensions:

                for e in _make_speed_extensions(gps_data, 0):
                    tp.extensions.append(e)

            track_segment.points.append(tp)

    return track_segment, starttime