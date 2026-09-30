

def test_resource_governance_route_exists():
    from autonomy.resource_governance_api import router

    routes = {
        route.path
        for route in router.routes
    }

    assert "/autonomy/resources/{resource_type}/{resource_id}/governance" in routes
