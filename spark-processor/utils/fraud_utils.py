from pyspark.sql.functions import udf
from pyspark.sql.types import DoubleType
import math


@udf(DoubleType())
def haversine_udf(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance in kilometers between two GPS coordinates.
    Used for distance_from_last_txn_km feature.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    R = 6371
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(R * c, 2)