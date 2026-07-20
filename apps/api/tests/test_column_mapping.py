from app.column_mapping import heuristic_match, resolve_column_mapping


def test_heuristic_match_exact_alias():
    assert heuristic_match("Total Amount", "sales") == ("totalAmount", 1.0)
    assert heuristic_match("Qty", "sales") == ("quantity", 1.0)
    assert heuristic_match("SKU", "inventory") == ("sku", 1.0)
    assert heuristic_match("Vendor", "expenses") == ("vendor", 1.0)


def test_heuristic_match_case_and_whitespace_insensitive():
    assert heuristic_match("  unit_price  ", "sales") == ("unitPrice", 1.0)


def test_heuristic_match_no_field_for_nonsense_header():
    match = heuristic_match("zzz_completely_unrelated_zzz", "sales")
    assert match is not None
    assert match[1] < 0.75


def test_resolve_column_mapping_uses_heuristic_when_confident():
    result = resolve_column_mapping("Total Amount", "sales", ["45.00", "120.00"])
    assert result == {"targetField": "totalAmount", "confidenceScore": 1.0, "mappingMethod": "heuristic"}


def test_resolve_column_mapping_falls_back_to_llm_when_ambiguous(monkeypatch):
    import app.column_mapping as column_mapping

    monkeypatch.setattr(column_mapping, "llm_match", lambda header, dataset_type, samples: ("productName", 0.55))

    result = column_mapping.resolve_column_mapping("X1", "sales", ["Rice", "Batteries"])
    assert result == {"targetField": "productName", "confidenceScore": 0.55, "mappingMethod": "llm"}
