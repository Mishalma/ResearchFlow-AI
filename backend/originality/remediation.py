from __future__ import annotations


def build_remediation_actions(*, classification: str, cited_nearby: bool, quoted: bool) -> list[str]:
    if classification == "quoted_and_cited":
        return ["verify_quote_scope_matches_the_cited_source"]
    if classification == "common_phrase":
        return ["no_action_required_common_phrase"]
    if classification == "boilerplate":
        return ["verify_reuse_permissions_if_required"]
    if classification == "possible_self_overlap":
        return [
            "review_self_overlap_disclosure_requirements",
            "confirm_reuse_is_permitted_by_the_target_venue",
        ]
    if classification == "uncited_close_paraphrase":
        actions = ["add_inline_citation_to_the_supporting_source"]
        if not quoted:
            actions.append("rewrite_from_the_underlying_evidence_in_original_wording_while_retaining_attribution")
        return actions
    if classification == "likely_unattributed_copying":
        actions = [
            "convert_to_a_direct_quote_with_attribution_if_verbatim_language_is_required",
            "otherwise_replace_with_original_synthesis_and_keep_citation",
            "manual_editor_review_required_before_release",
        ]
        if cited_nearby:
            actions.insert(0, "verify_the_existing_citation_actually_covers_the_overlapping_language")
        return actions
    return [
        "review_the_source_relationship_manually",
        "add_or_correct_attribution_before_release",
    ]
