
def test_governance_api_is_explicitly_read_only():
    from autonomy.resource_governance_api import router

    route = next(
        route
        for route in router.routes
        if route.path.endswith("/governance")
    )

    assert set(route.methods or []) == {"GET"}
