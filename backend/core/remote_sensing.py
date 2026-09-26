import numpy as np

def safe_divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Safe division to avoid divide by zero in raster math."""
    with np.errstate(divide='ignore', invalid='ignore'):
        result = np.divide(numerator, denominator)
        # Replace NaNs or Infs with 0
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    return result

def calculate_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    Normalized Difference Water Index (NDWI)
    Formula: (Green - NIR) / (Green + NIR)
    Useful for delineating water bodies.
    """
    return safe_divide((green - nir), (green + nir))

def calculate_ndti(red: np.ndarray, green: np.ndarray) -> np.ndarray:
    """
    Normalized Difference Turbidity Index (NDTI)
    Formula: (Red - Green) / (Red + Green)
    Estimates turbidity/suspended sediment in water.
    """
    return safe_divide((red - green), (red + green))

def calculate_ndci(red_edge: np.ndarray, red: np.ndarray) -> np.ndarray:
    """
    Normalized Difference Chlorophyll Index (NDCI)
    Formula: (Red_Edge - Red) / (Red_Edge + Red)
    Estimates chlorophyll-a concentration (algal blooms).
    """
    return safe_divide((red_edge - red), (red_edge + red))

def generate_mock_sentinel_scene(size: tuple = (256, 256)) -> dict:
    """
    Generates synthetic Sentinel-2 spectral bands for testing the pipeline
    before plugging in actual heavy raster data.
    """
    # Create random base layers for bands between 0 and 10000 (standard S2 reflectance scaling)
    return {
        "green": np.random.uniform(500, 1500, size),     # Band 3
        "red": np.random.uniform(300, 1200, size),       # Band 4
        "red_edge": np.random.uniform(400, 1300, size),  # Band 5
        "nir": np.random.uniform(200, 2500, size)        # Band 8
    }

def process_scene_indices(scene: dict) -> dict:
    """
    Calculates all relevant spectral indices for a given scene.
    """
    return {
        "ndwi": calculate_ndwi(scene["green"], scene["nir"]),
        "ndti": calculate_ndti(scene["red"], scene["green"]),
        "ndci": calculate_ndci(scene["red_edge"], scene["red"])
    }
