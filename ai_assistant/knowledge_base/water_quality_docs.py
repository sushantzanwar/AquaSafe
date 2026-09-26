"""
AquaWatch Scientific Knowledge Base
=====================================
Authentic scientific text about Sentinel-2 water quality indicators,
WHO guidelines, and lake health assessment.

This is used by the ChromaDB vector store to give the RAG AI
real, grounded scientific context when answering questions.
"""

SCIENTIFIC_DOCUMENTS = [

    # ── SENTINEL-2 BANDS ────────────────────────────────────────────
    {
        "id": "s2_bands_overview",
        "topic": "Sentinel-2 Bands",
        "text": (
            "Sentinel-2 is a European Space Agency (ESA) multispectral satellite. "
            "It carries a MultiSpectral Instrument (MSI) sampling 13 spectral bands. "
            "The bands relevant for water quality are: "
            "Band 2 (Blue, 490nm), Band 3 (Green, 560nm), Band 4 (Red, 665nm), "
            "Band 5 (Red-Edge 1, 705nm), Band 6 (Red-Edge 2, 740nm), "
            "Band 7 (Red-Edge 3, 783nm), Band 8 (NIR, 842nm), and Band 8A (Narrow NIR, 865nm). "
            "Spatial resolution: 10m for Blue/Green/Red/NIR bands, 20m for Red-Edge bands. "
            "Revisit time is 5 days over India, enabling near-real-time monitoring."
        )
    },

    # ── NDWI ──────────────────────────────────────────────────────
    {
        "id": "ndwi_definition",
        "topic": "NDWI Water Index",
        "text": (
            "NDWI (Normalized Difference Water Index) is calculated as (Green - NIR) / (Green + NIR). "
            "It uses Sentinel-2 Band 3 (Green) and Band 8 (NIR). "
            "NDWI > 0 indicates water surface. "
            "NDWI values between 0.2 and 0.8 indicate open water bodies. "
            "Values below 0.0 indicate land or built-up areas. "
            "NDWI is used for delineating water body boundaries and monitoring lake surface area changes. "
            "A sudden drop in NDWI can indicate drought stress or siltation reducing the effective water area."
        )
    },

    # ── NDTI ──────────────────────────────────────────────────────
    {
        "id": "ndti_definition",
        "topic": "NDTI Turbidity Index",
        "text": (
            "NDTI (Normalized Difference Turbidity Index) is calculated as (Red - Green) / (Red + Green). "
            "It uses Sentinel-2 Band 4 (Red) and Band 3 (Green). "
            "Higher NDTI values indicate higher turbidity (more suspended sediment or organic matter). "
            "NDTI > 0.10 typically signals elevated turbidity. "
            "NDTI > 0.25 is associated with high suspended sediment loads from runoff or resuspension. "
            "Turbidity impedes photosynthesis in aquatic plants and affects fish habitats. "
            "Seasonal spikes in NDTI after monsoon rains are normal, but sudden non-seasonal spikes are anomalous."
        )
    },
    {
        "id": "ndti_anomaly_detection",
        "topic": "NDTI Anomaly Detection",
        "text": (
            "Anomaly detection in NDTI uses a time-series baseline approach. "
            "A baseline mean and standard deviation are calculated from historical NDTI values "
            "for each lake over a 90-day rolling window. "
            "A current observation is flagged as anomalous if its NDTI deviates by more than "
            "1.5 standard deviations (sigma) from the baseline mean. "
            "A deviation greater than 2 sigma indicates HIGH anomaly status. "
            "This statistical approach avoids false positives from seasonal variation and "
            "focuses the system on genuine, unexpected optical changes in the water column."
        )
    },

    # ── NDCI ──────────────────────────────────────────────────────
    {
        "id": "ndci_definition",
        "topic": "NDCI Chlorophyll Index",
        "text": (
            "NDCI (Normalized Difference Chlorophyll Index) is calculated as "
            "(Red-Edge - Red) / (Red-Edge + Red). "
            "It uses Sentinel-2 Band 5 (Red-Edge 1, 705nm) and Band 4 (Red, 665nm). "
            "NDCI is sensitive to phytoplankton and algal chlorophyll concentration. "
            "NDCI > 0.05 indicates elevated chlorophyll; NDCI > 0.15 strongly indicates algal bloom conditions. "
            "High NDCI values during summer months are associated with eutrophication driven by "
            "excess nutrients (nitrogen and phosphorus) from agricultural runoff and sewage discharge."
        )
    },
    {
        "id": "ndci_algal_bloom",
        "topic": "Algal Blooms and NDCI",
        "text": (
            "Algal blooms occur when phytoplankton populations grow rapidly, depleting oxygen "
            "and producing toxins harmful to fish, animals, and humans. "
            "In India, cyanobacteria (blue-green algae) blooms are the most dangerous type, "
            "producing hepatotoxins (microcystin) and neurotoxins (cylindrospermopsin). "
            "NDCI > 0.15 combined with NDWI > 0.30 is a strong indicator of active bloom conditions. "
            "Sentinel-2 can detect bloom initiation 3–5 days before it becomes visible to the naked eye. "
            "Field verification is required before issuing public health advisories based on remote sensing alone."
        )
    },

    # ── TURBIDITY & WATER QUALITY ──────────────────────────────────
    {
        "id": "turbidity_health_impacts",
        "topic": "Turbidity and Public Health",
        "text": (
            "Turbidity is a measure of the cloudiness of water caused by suspended particles. "
            "It is measured in Nephelometric Turbidity Units (NTU). "
            "WHO drinking water guidelines set an upper limit of 1 NTU for treated drinking water "
            "and 5 NTU as an operational limit. "
            "High turbidity in source water increases chlorine demand, allows pathogens to hide "
            "behind particles, and signals potential contamination. "
            "Turbidity above 50 NTU is typically considered highly impacted and unsafe for direct use. "
            "NDTI values from Sentinel-2 correlate with turbidity (NTU) with an R² > 0.82 in most Indian lakes."
        )
    },
    {
        "id": "turbidity_causes",
        "topic": "Causes of Elevated Turbidity",
        "text": (
            "Common causes of elevated turbidity in Indian lakes include: "
            "(1) Surface runoff during and after monsoon rains carrying soil, agricultural debris, and fertilizers. "
            "(2) Resuspension of bottom sediments by wind action in shallow lakes. "
            "(3) Untreated sewage and industrial effluent discharge increasing suspended organic matter. "
            "(4) Construction activity near water bodies releasing silt. "
            "(5) Algal blooms decaying and releasing organic particulates. "
            "Distinguishing between these causes requires both remote sensing indicators and field sampling."
        )
    },

    # ── LAKE HEALTH & EUTROPHICATION ──────────────────────────────
    {
        "id": "eutrophication",
        "topic": "Eutrophication",
        "text": (
            "Eutrophication is the process where water bodies receive excess nutrients—primarily "
            "nitrogen and phosphorus—leading to dense algal growth and oxygen depletion. "
            "Stages: Oligotrophic (clean, low nutrients), Mesotrophic (moderate), "
            "Eutrophic (high nutrients, algal blooms), Hypereutrophic (severe oxygen depletion, fish kills). "
            "Most urban lakes in Nagpur, Maharashtra are in a Eutrophic to Hypereutrophic state "
            "due to untreated sewage inflows. "
            "NDCI > 0.10 combined with persistent high NDTI indicates advanced eutrophication. "
            "Recovery requires source control (sewage treatment) and in-lake interventions like aeration."
        )
    },
    {
        "id": "india_lake_status",
        "topic": "Lake Health in India",
        "text": (
            "India has over 10,000 lakes and ponds, many under severe stress from urbanization. "
            "The Central Pollution Control Board (CPCB) classifies water quality in five categories: "
            "A (drinking water), B (bathing), C (drinking with conventional treatment), "
            "D (wildlife/fisheries), E (irrigation). "
            "Most urban Indian lakes have degraded from Class B to Class D or E. "
            "Ambazari Lake (Nagpur) and Gorewada Lake (Nagpur) are important urban reservoirs "
            "that supply drinking water after treatment and are closely monitored by NMC (Nagpur Municipal Corporation). "
            "Early anomaly detection via Sentinel-2 provides a 3–7 day advance warning window for water treatment plant operators."
        )
    },

    # ── BASELINE COMPARISON METHODOLOGY ────────────────────────────
    {
        "id": "baseline_methodology",
        "topic": "Baseline Anomaly Detection Methodology",
        "text": (
            "AquaWatch uses a statistical baseline comparison approach consistent with ESA Copernicus "
            "water quality monitoring standards. "
            "For each lake, a rolling 90-day baseline is computed from historical Sentinel-2 observations. "
            "The baseline stores mean (μ) and standard deviation (σ) for NDTI, NDCI, and NDWI. "
            "Anomaly score = (current_value - μ) / σ  (Z-score or sigma deviation). "
            "NORMAL status: deviation < 1.0 sigma. "
            "WARNING status: deviation between 1.0 and 1.75 sigma. "
            "HIGH status: deviation > 1.75 sigma. "
            "Anomalous area percentage refers to the fraction of lake pixels exceeding the HIGH threshold. "
            "This approach avoids seasonal false positives and is more reliable than single-image thresholds."
        )
    },

    # ── GROUND TRUTH VERIFICATION ──────────────────────────────────
    {
        "id": "ground_truth",
        "topic": "Ground Verification",
        "text": (
            "Satellite-derived water quality indicators are decision-support tools, not definitive diagnoses. "
            "The WHO and CPCB recommend that satellite anomaly flags should trigger field verification "
            "within 24-72 hours for HIGH anomaly status. "
            "Field parameters to measure include: pH, Dissolved Oxygen (DO), Biochemical Oxygen Demand (BOD), "
            "Total Dissolved Solids (TDS), Turbidity (NTU), Fecal Coliform count, and Chlorophyll-a. "
            "Remote sensing flags paired with field data provide the evidentiary basis for "
            "issuing public health advisories or enforcement action against polluters. "
            "Without field confirmation, satellite data alone should be communicated as an 'optical anomaly' "
            "rather than a definitive contamination event."
        )
    },

    # ── SENTINEL-2 WATER MONITORING STANDARDS ──────────────────────
    {
        "id": "esa_water_monitoring",
        "topic": "ESA Sentinel-2 Water Quality Monitoring",
        "text": (
            "ESA's Copernicus programme provides free access to Sentinel-2 data through the "
            "Copernicus Open Access Hub (Scihub) and the Copernicus Data Space Ecosystem. "
            "For water quality monitoring, the recommended Level-2A (surface reflectance) product is used. "
            "Atmospheric correction is critical for water targets; ACOLITE and Sen2Cor are standard tools. "
            "The Copernicus Global Land Service provides pre-computed water quality products including "
            "chlorophyll-a, turbidity, CDOM (colored dissolved organic matter), and lake surface temperature. "
            "Revisit frequency of 5 days makes Sentinel-2 ideal for near-real-time monitoring "
            "of Indian lakes, reservoirs, and wetlands."
        )
    },

    # ── NAGPUR SPECIFIC ────────────────────────────────────────────
    {
        "id": "nagpur_lakes",
        "topic": "Nagpur Lakes",
        "text": (
            "Nagpur, Maharashtra is home to several important urban lakes. "
            "Ambazari Lake (area: ~6 km²) is a key drinking water reservoir. "
            "Futala Lake is a recreational urban lake known for algal bloom events in summer. "
            "Gorewada Lake is part of the Gorewada International Zoo and Biodiversity Park. "
            "Sonegaon Lake and Gandhisagar Lake serve recreational and groundwater recharge purposes. "
            "All Nagpur lakes face pressure from encroachment, sewage inflows, and solid waste dumping. "
            "NMC and WWF India have been running lake conservation programs since 2018. "
            "Satellite monitoring supports these conservation efforts by providing low-cost, frequent observations."
        )
    },
]
