"""Documented columns of a ZTBus driving mission file (Table 1 of the dataset paper)."""

DOCUMENTED_COLUMNS = [
    "time_iso", "time_unix", "electric_powerDemand",
    "gnss_altitude", "gnss_course", "gnss_latitude", "gnss_longitude",
    "itcs_busRoute", "itcs_numberOfPassengers", "itcs_stopName",
    "odometry_articulationAngle", "odometry_steeringAngle", "odometry_vehicleSpeed",
    "odometry_wheelSpeed_fl", "odometry_wheelSpeed_fr", "odometry_wheelSpeed_ml",
    "odometry_wheelSpeed_mr", "odometry_wheelSpeed_rl", "odometry_wheelSpeed_rr",
    "status_doorIsOpen", "status_gridIsAvailable",
    "status_haltBrakeIsActive", "status_parkBrakeIsActive",
    "temperature_ambient", "traction_brakePressure", "traction_tractionForce",
]