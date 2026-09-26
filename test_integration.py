import httpx

base_url = "http://localhost:8000"

def run_tests():
    print("--- AquaWatch E2E Integration Test ---")
    
    # 1. Test /api/water-bodies
    print("\n[1] Testing /api/water-bodies...")
    try:
        r = httpx.get(f"{base_url}/api/water-bodies?lat=21.15&lon=79.09&radius_km=15", timeout=15)
        r.raise_for_status()
        data = r.json()
        print(f"[OK] Found {len(data.get('water_bodies', []))} water bodies nearby.")
    except Exception as e:
        print(f"[FAIL] {e}")
        return

    # 2. Test /api/analyze
    print("\n[2] Testing /api/analyze (Core Pipeline)...")
    analysis_id = None
    try:
        payload = {"water_body": "Ambazari Lake", "date": "2026-09-26"}
        r = httpx.post(f"{base_url}/api/analyze", json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        analysis_id = data.get("analysis_id")
        status = data.get("anomaly", {}).get("status")
        score = data.get("anomaly", {}).get("score")
        
        print(f"[OK] Created Analysis ID: {analysis_id}")
        print(f"   -> Anomaly Status: {status} (Score: {score})")
        print(f"   -> GeoJSON features: {len(data.get('geojson', {}).get('features', []))}")
    except Exception as e:
        print(f"[FAIL] {e}")
        return

    # 3. Test /api/analysis/{id}/explain (RAG Agent)
    print("\n[3] Testing /api/analysis/{id}/explain (RAG Agent + ChromaDB)...")
    try:
        payload = {"user_question": "What does high NDCI mean and why is it dangerous?"}
        r = httpx.post(f"{base_url}/api/analysis/{analysis_id}/explain", json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        explanation = data.get("explanation", "")
        
        print(f"[OK] AI responded with {len(explanation)} characters.")
        print(f"\n--- AI RESPONSE PREVIEW ---")
        print(explanation)
        print("---------------------------\n")
        
        if "chlorophyll" in explanation.lower() or "bloom" in explanation.lower():
            print("[OK] Verification: AI successfully retrieved ChromaDB context!")
        else:
            print("[WARN] AI response might not have used ChromaDB context properly.")
            
    except Exception as e:
        print(f"[FAIL] {e}")
        return
        
    print("\nAll End-to-End systems are GO!")

if __name__ == "__main__":
    run_tests()
