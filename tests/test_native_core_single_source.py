def test_native_core_has_one_runtime_source_tree(project_root):
    assert not (project_root / "interest_growth_native/__init__.py").exists()
    assert (project_root / "packages/native-execution-core/interest_growth_native").is_dir()


def test_native_core_package_is_importable_from_its_owner_tree(project_root):
    import sys

    sys.path.insert(0, str(project_root / "packages/native-execution-core"))
    import interest_growth_native

    assert interest_growth_native.__version__ == "0.6.0rc2"
