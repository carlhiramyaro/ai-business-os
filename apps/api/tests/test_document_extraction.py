from app.document_extraction import _parse_extraction_response


def test_parse_extraction_keeps_only_canonical_fields():
    raw = {
        "rows": [
            {"saleDate": "2026-07-24", "productName": "Rice", "quantity": 2, "totalAmount": "25.0"},
            {"saleDate": "2026-07-24", "productName": "Beans", "notARealField": "x"},
        ],
        "confidence": 0.8,
    }
    result = _parse_extraction_response(raw, "sales")

    assert result["rows"] == [
        {"saleDate": "2026-07-24", "productName": "Rice", "quantity": 2, "totalAmount": "25.0"},
        {"saleDate": "2026-07-24", "productName": "Beans"},
    ]
    assert result["confidence"] == 0.8


def test_parse_extraction_clamps_confidence_to_0_1():
    assert _parse_extraction_response({"rows": [], "confidence": 5.0}, "sales")["confidence"] == 1.0
    assert _parse_extraction_response({"rows": [], "confidence": -2.0}, "sales")["confidence"] == 0.0


def test_parse_extraction_invalid_confidence_defaults_to_zero():
    assert _parse_extraction_response({"rows": [], "confidence": "not a number"}, "sales")["confidence"] == 0.0
    assert _parse_extraction_response({"rows": []}, "sales")["confidence"] == 0.0


def test_parse_extraction_non_list_rows_becomes_empty():
    assert _parse_extraction_response({"rows": "garbage", "confidence": 0.5}, "sales")["rows"] == []


def test_parse_extraction_skips_non_dict_row_entries():
    raw = {"rows": [{"productName": "Rice"}, "not a dict", 42], "confidence": 0.5}
    assert _parse_extraction_response(raw, "sales")["rows"] == [{"productName": "Rice"}]


def test_parse_extraction_scoped_per_dataset_type():
    """A field valid for 'sales' (customerName) isn't valid for 'expenses'
    -- extraction must respect the dataset it was asked to extract for."""
    raw = {"rows": [{"customerName": "Ama", "vendor": "Power Co", "amount": "10.0"}], "confidence": 0.5}
    result = _parse_extraction_response(raw, "expenses")
    assert result["rows"] == [{"vendor": "Power Co", "amount": "10.0"}]
