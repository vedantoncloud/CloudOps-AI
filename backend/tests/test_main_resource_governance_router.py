
def test_main_registers_resource_governance_router():
    import main

    expected = "/autonomy/resources/{resource_type}/{resource_id}/governance"

    openapi_paths = set(main.app.openapi()["paths"])

    assert expected in openapi_paths, (
        f"Expected governance route not registered in OpenAPI. "
        f"Available autonomy paths: "
        f"{sorted(path for path in openapi_paths if path.startswith("/autonomy/"))}"
    )
