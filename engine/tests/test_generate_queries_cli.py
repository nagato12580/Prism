from pathlib import Path

from engine.eval import generate_queries


def test_parse_args_supports_target_items_sample_size_and_output():
    args = generate_queries.parse_args(
        [
            "--item-ids",
            "item-a",
            "item-b",
            "--sample-size",
            "12",
            "--output",
            "evaluation/datasets/formal_docs_v1.json",
            "--seed",
            "7",
        ]
    )

    assert args.item_ids == ["item-a", "item-b"]
    assert args.sample_size == 12
    assert args.output == "evaluation/datasets/formal_docs_v1.json"
    assert args.seed == 7


def test_default_output_points_to_legacy_golden_dataset():
    args = generate_queries.parse_args([])

    assert Path(args.output) == generate_queries.OUTPUT_PATH
