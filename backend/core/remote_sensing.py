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

def generate_mock_sentinel_scene(size: tuple = (256, 256), seed: int = 42) -> dict:
    """
    Generates synthetic Sentinel-2 spectral bands for testing the pipeline.
    """
    np.random.seed(seed)
    return {
        "green": np.random.uniform(500, 1500, size),     # Band 3
        "red": np.random.uniform(300, 1200, size),       # Band 4
        "red_edge": np.random.uniform(400, 1300, size),  # Band 5
        "nir": np.random.uniform(200, 2500, size)        # Band 8
    }

def generate_realistic_sentinel_scene(lat: float = 21.129, lng: float = 79.039, size: tuple = (512, 512), date_str: str = "2026-09-25") -> dict:
    """
    Generates realistic spatial Sentinel-2 L2A spectral bands with a water body contour,
    shoreline, sediment plume, and surrounding terrain based on coordinates.
    """
    # Deterministic seed based on location and date
    seed_str = f"{lat:.4f}_{lng:.4f}_{date_str}"
    seed = int(sum(ord(c) for c in seed_str)) % 100000
    np.random.seed(seed)
    
    h, w = size
    y, x = np.ogrid[:h, :w]
    cy, cx = h / 2.0, w / 2.0
    
    # Create water body contour (irregular ellipse with noise)
    dist_from_center = np.sqrt(((x - cx) / (w * 0.35))**2 + ((y - cy) / (h * 0.28))**2)
    
    # Add spatial wave/contour variations
    angle = np.arctan2(y - cy, x - cx)
    noise_contour = 0.12 * np.sin(4 * angle) + 0.08 * np.cos(7 * angle) + 0.05 * np.sin(12 * angle)
    is_water = (dist_from_center + noise_contour) < 1.0
    
    # Water depth/dist gradient
    water_depth = np.clip(1.0 - (dist_from_center + noise_contour), 0.0, 1.0)
    
    # Plume / Sediment anomaly area near north-east shore
    plume_dist = np.sqrt(((x - (cx + w * 0.15)) / (w * 0.18))**2 + ((y - (cy - h * 0.15)) / (h * 0.15))**2)
    plume_intensity = np.clip(1.0 - plume_dist, 0.0, 1.0) * is_water
    
    # Band 2 (Blue), Band 3 (Green), Band 4 (Red), Band 5 (Red Edge), Band 8 (NIR)
    # Land values vs Water values (Sentinel-2 L2A reflectance scaled 0-10000)
    blue = np.where(is_water, 800 + 400 * water_depth + 600 * plume_intensity, 1200 + 300 * np.random.rand(h, w))
    green = np.where(is_water, 900 + 300 * water_depth + 900 * plume_intensity, 1400 + 400 * np.random.rand(h, w))
    red = np.where(is_water, 400 + 100 * water_depth + 1100 * plume_intensity, 1600 + 500 * np.random.rand(h, w))
    red_edge = np.where(is_water, 500 + 200 * water_depth + 800 * plume_intensity, 2400 + 800 * np.random.rand(h, w))
    nir = np.where(is_water, 300 + 100 * water_depth, 3200 + 1000 * np.random.rand(h, w))
    
    # Add subtle sensor noise
    sensor_noise = np.random.normal(0, 15, size)
    
    return {
        "blue": np.clip(blue + sensor_noise, 0, 10000),
        "green": np.clip(green + sensor_noise, 0, 10000),
        "red": np.clip(red + sensor_noise, 0, 10000),
        "red_edge": np.clip(red_edge + sensor_noise, 0, 10000),
        "nir": np.clip(nir + sensor_noise, 0, 10000),
        "is_water": is_water,
        "plume": plume_intensity
    }

def render_satellite_image_png(scene: dict, mode: str = "rgb") -> bytes:
    """
    Renders Sentinel-2 scene as high-definition PNG image bytes.
    Modes:
      - 'rgb': True Color RGB (B4, B3, B2)
      - 'false_color': Near Infrared False Color (B8, B4, B3)
      - 'ndwi': NDWI Water Index Heatmap (Cyan/Blue water, dark land)
      - 'ndti': NDTI Turbidity Heatmap (Vibrant Yellow/Red sediment plume)
      - 'ndci': NDCI Chlorophyll Algal Bloom Heatmap (Neon Green/Purple bloom)
    """
    from PIL import Image
    from io import BytesIO
    
    h, w = scene["red"].shape
    
    if mode == "rgb":
        # True Color RGB
        r = np.clip((scene["red"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        g = np.clip((scene["green"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        b = np.clip((scene["blue"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        rgb = np.dstack((r, g, b))
        
    elif mode == "false_color":
        # CIR (Color Infrared): R = NIR (B8), G = Red (B4), B = Green (B3)
        r = np.clip((scene["nir"] / 4000.0) * 255, 0, 255).astype(np.uint8)
        g = np.clip((scene["red"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        b = np.clip((scene["green"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        rgb = np.dstack((r, g, b))
        
    elif mode == "ndwi":
        # NDWI Heatmap: (Green - NIR) / (Green + NIR)
        ndwi = safe_divide((scene["green"] - scene["nir"]), (scene["green"] + scene["nir"]))
        # Color mapping: Land = Dark Grey, Water = Deep Cyan/Blue
        r = np.where(scene["is_water"], np.clip((1 - ndwi) * 40, 0, 100), 40).astype(np.uint8)
        g = np.where(scene["is_water"], np.clip((ndwi + 0.5) * 200, 100, 255), 45).astype(np.uint8)
        b = np.where(scene["is_water"], np.clip((ndwi + 0.5) * 255, 150, 255), 50).astype(np.uint8)
        rgb = np.dstack((r, g, b))
        
    elif mode == "ndti":
        # NDTI Turbidity Heatmap: (Red - Green) / (Red + Green)
        ndti = safe_divide((scene["red"] - scene["green"]), (scene["red"] + scene["green"]))
        # Color mapping: Clear Water = Deep Blue, High Turbidity Plume = Bright Yellow/Red
        r = np.where(scene["is_water"], np.clip((ndti + 0.2) * 450, 20, 255), 35).astype(np.uint8)
        g = np.where(scene["is_water"], np.clip(220 - (ndti + 0.2) * 300, 20, 220), 40).astype(np.uint8)
        b = np.where(scene["is_water"], np.clip(255 - (ndti + 0.2) * 500, 20, 255), 45).astype(np.uint8)
        rgb = np.dstack((r, g, b))
        
    elif mode == "ndci":
        # NDCI Chlorophyll Heatmap: (Red_Edge - Red) / (Red_Edge + Red)
        ndci = safe_divide((scene["red_edge"] - scene["red"]), (scene["red_edge"] + scene["red"]))
        # Color mapping: Low Chlorophyll = Deep Blue, Algal Bloom = Neon Green / Magenta
        r = np.where(scene["is_water"], np.clip((ndci + 0.1) * 350, 30, 255), 30).astype(np.uint8)
        g = np.where(scene["is_water"], np.clip((ndci + 0.2) * 500, 50, 255), 35).astype(np.uint8)
        b = np.where(scene["is_water"], np.clip(180 - (ndci + 0.1) * 300, 20, 200), 40).astype(np.uint8)
        rgb = np.dstack((r, g, b))
        
    else:
        # Default RGB fallback
        r = np.clip((scene["red"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        g = np.clip((scene["green"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        b = np.clip((scene["blue"] / 2000.0) * 255, 0, 255).astype(np.uint8)
        rgb = np.dstack((r, g, b))
        
    img = Image.fromarray(rgb, mode="RGB")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def process_scene_indices(scene: dict) -> dict:
    """
    Calculates all relevant spectral indices for a given scene.
    """
    return {
        "ndwi": calculate_ndwi(scene["green"], scene["nir"]),
        "ndti": calculate_ndti(scene["red"], scene["green"]),
        "ndci": calculate_ndci(scene["red_edge"], scene["red"])
    }

