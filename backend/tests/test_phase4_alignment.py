from app.domain.transformation import OutputType
from app.models import SourceRegion
from app.source_alignment import RegionRef, align_regions


def region(
    region_id: int,
    text: str,
    *,
    locator: str | None = None,
    ordinal: int | None = None,
    asset_id: int = 1,
) -> RegionRef:
    region_ordinal = ordinal if ordinal is not None else region_id
    return RegionRef(
        SourceRegion(
            id=region_id,
            source_asset_id=asset_id,
            ordinal=region_ordinal,
            locator=locator or f"paragraph:{region_ordinal}",
            region_type="paragraph",
            page_number=None,
            text=text,
        ),
        "PRIMARY",
        1,
    )


def states(old: list[RegionRef], new: list[RegionRef]) -> list[str]:
    return [item.state for item in align_regions(old, new)]


def test_source_alignment_covers_all_eight_states_without_guessing() -> None:
    fixtures = {
        "unchanged": states(
            [region(1, "Same.", locator="paragraph:1")],
            [region(2, "Same.", locator="paragraph:1")],
        ),
        "moved": states(
            [region(3, "Moved.", locator="paragraph:1")],
            [region(4, "Moved.", locator="paragraph:2")],
        ),
        "ambiguous": states(
            [region(5, "Duplicate.", locator="paragraph:1")],
            [
                region(6, "Duplicate.", locator="paragraph:2"),
                region(7, "Duplicate.", locator="paragraph:3"),
            ],
        ),
        "changed": states(
            [region(8, "Old wording.", locator="paragraph:1")],
            [region(9, "New wording.", locator="paragraph:1")],
        ),
        "removed": states([region(10, "Removed.")], []),
        "added": states([], [region(11, "Added.")]),
        "split": states(
            [region(12, "First part. Second part.", asset_id=2)],
            [
                region(13, "First part.", ordinal=1, asset_id=3),
                region(14, "Second part.", ordinal=2, asset_id=3),
            ],
        ),
        "merged": states(
            [
                region(15, "First part.", ordinal=1, asset_id=4),
                region(16, "Second part.", ordinal=2, asset_id=4),
            ],
            [region(17, "First part. Second part.", asset_id=5)],
        ),
    }

    assert fixtures["unchanged"] == ["unchanged"]
    assert fixtures["moved"] == ["moved"]
    assert set(fixtures["ambiguous"]) == {"ambiguous"}
    assert fixtures["changed"] == ["changed"]
    assert fixtures["removed"] == ["removed"]
    assert fixtures["added"] == ["added"]
    assert set(fixtures["split"]) == {"split"}
    assert set(fixtures["merged"]) == {"merged"}


def test_artifact_blocks_cover_claim_scan_projection_for_all_seven_families() -> None:
    from app.artifact_contracts import (
        InfographicCalloutBlock,
        InfographicDataBlock,
        InfographicDataPoint,
        InfographicSectionBlock,
        InfographicSpec,
        VideoPackageSpec,
        VideoSceneSpec,
        artifact_text_projection,
        canonical_json,
    )
    from app.artifact_lineage import block_inventory_covers_projection, extract_artifact_blocks
    from app.presentation import PresentationSpec, SlideSpec

    contents = {
        OutputType.EXECUTIVE_SUMMARY: "First paragraph.\n\nSecond paragraph.",
        OutputType.LINKEDIN_POST: "A short post.",
        OutputType.X_POST: "A short post.",
        OutputType.ADVISORY: "Heading.\n\nAdvisory detail.",
        OutputType.PRESENTATION: canonical_json(
            PresentationSpec(
                title="Deck title",
                slides=[
                    SlideSpec(
                        title="Slide title",
                        key_message="Slide message.",
                        bullets=["Slide bullet."],
                        visual_recommendation="A map marker.",
                        speaker_notes="Speaker note.",
                    ),
                    SlideSpec(
                        title="Second slide",
                        key_message="Second message.",
                        bullets=["Second bullet."],
                        visual_recommendation="A town map.",
                        speaker_notes="Second speaker note.",
                    ),
                ],
            )
        ),
        OutputType.INFOGRAPHIC: canonical_json(
            InfographicSpec(
                title="Infographic title",
                subtitle="Infographic subtitle",
                key_message="Infographic message.",
                blocks=[
                    InfographicSectionBlock(heading="Section", body="Section body."),
                    InfographicCalloutBlock(
                        label="Callout", value="42", explanation="Callout note."
                    ),
                    InfographicDataBlock(
                        heading="Table",
                        rows=[
                            InfographicDataPoint(label="Visitors", value="42", note="As of May.")
                        ],
                    ),
                ],
                visual_direction="Use a bar chart.",
            )
        ),
        OutputType.VIDEO_PACKAGE: canonical_json(
            VideoPackageSpec(
                title="Video title",
                concept="Video concept.",
                scenes=[
                    VideoSceneSpec(
                        title="Scene title",
                        narration="Narration.",
                        on_screen_text=["On-screen text."],
                        visual_direction="Show the entrance.",
                        transition_notes="Cut to the next scene.",
                    )
                ],
            )
        ),
    }

    assert set(contents) == set(OutputType)
    for output_type, content in contents.items():
        blocks = extract_artifact_blocks(output_type, content)
        projection = artifact_text_projection(output_type, content)
        assert block_inventory_covers_projection(output_type, content)
        assert all(block.visible_text in projection for block in blocks)
        if output_type == OutputType.INFOGRAPHIC:
            assert {
                "title",
                "heading",
                "body",
                "callout_label",
                "callout_value",
                "data_label",
                "data_value",
            }.issubset({block.block_type for block in blocks})
        if output_type == OutputType.VIDEO_PACKAGE:
            assert {
                "title",
                "concept",
                "narration",
                "on_screen_text",
                "visual_direction",
                "transition_notes",
            }.issubset({block.block_type for block in blocks})
        if output_type == OutputType.PRESENTATION:
            assert {"title", "key_message", "bullet", "speaker_notes", "visual_direction"}.issubset(
                {block.block_type for block in blocks}
            )
