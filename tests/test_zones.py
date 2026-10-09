from vision_rules import inside


def test_inside_includes_boundaries():
    assert inside((10, 20), (10, 20, 30, 40))
    assert inside((25, 35), (10, 20, 30, 40))
    assert not inside((31, 35), (10, 20, 30, 40))

