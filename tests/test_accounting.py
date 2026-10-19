"""Accounting: the partition, the recognition states and the strict bar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_classpath_dump import DUMP, declaration, type_doc, write_inventory


def _registry(**changes):
    return {
        "actions": [],
        "effects": [],
        "lifecycle": [],
        "modifiers": {},
        "components": {},
        "valueTypes": {},
    } | changes


def _report(**changes):
    report = {
        "pin": {"bom": "2026.09.00", "compiler": "2.4.21"},
        "denominator": {"declarations": 4, "dispositions": {"ui": 2, "support": 2}},
        "domains": {
            "material": {
                "declarations": {"ui": 2, "support": 2},
                "overloads": {"approved": 1, "blocked": 1},
            }
        },
        "supportRecognition": {"approved": 2},
        "grounding": {"ungroundedComponents": [], "ungroundedValues": []},
        "gaps": {
            "classes": {"value-binding": 1},
            "unclassifiedReasons": {},
            "diagnostics": [],
        },
    }
    return report | changes


def _support(name: str = "member", descriptor: str = "()V", **changes):
    from tools.schema.classpath_dump import Declaration

    record = {
        "owner": "androidx.compose.material3.Holder",
        "disposition": "support",
        "composable": False,
    } | changes
    return Declaration.read(declaration(name, descriptor, **record))


def test_normalize_joins_nested_classifiers() -> None:
    from tools.schema.accounting_views import normalize

    assert (
        normalize("androidx/compose/ui/Alignment$Companion")
        == "androidx.compose.ui.Alignment.Companion"
    )
    assert normalize("androidx.compose.ui.Alignment") == "androidx.compose.ui.Alignment"


def test_domain_of_reads_receivers_then_the_longest_owner_prefix() -> None:
    from tools.schema.accounting import MODIFIER, domain_of

    assert domain_of("androidx.compose.material3", [MODIFIER]) == "modifiers"
    assert (
        domain_of("androidx.compose.material3.adaptive.navigationsuite", [])
        == "navigation"
    )
    assert domain_of("androidx.compose.material3", []) == "material"
    assert domain_of("androidx.compose.ui.text.style", []) == "text"
    assert domain_of("androidx.compose.ui", []) == "foundation"
    assert domain_of("androidx.navigationevent.compose", []) == "navigation"
    assert domain_of("androidx.navigation3.runtime", []) == "navigation"
    # Dot boundaries decide: a sibling package is not a prefix match.
    assert domain_of("androidx.navigationevent", []) == "navigation"
    assert domain_of("androidx.compose.material3x", []) == "unclassified"
    assert domain_of("androidx.material", []) == "unclassified"


def test_gap_class_names_the_work_each_reason_needs() -> None:
    from tools.schema.accounting import gap_class

    assert (
        gap_class("no wire policy for androidx/compose/ui/Modifier") == "value-binding"
    )
    assert gap_class("default: source could not be pinned") == "defaults-evidence"
    assert gap_class("missing compiler-resolved default") == "defaults-evidence"
    assert (
        gap_class("receiver/generic declaration needs a native protocol")
        == "runtime-protocol"
    )
    assert (
        gap_class("synchronous result needs a provider/predicate protocol")
        == "provider-protocol"
    )
    assert gap_class("an unknown reason") == "unclassified"


def test_placement_keeps_every_candidate_in_one_bucket() -> None:
    from tools.schema.accounting_views import placement as _placement

    approved = {"androidx.compose.material3.Text"}
    component = {"surface": "component", "call": "androidx.compose.material3.Text"}
    assert _placement(component | {"status": "call-plan"}, approved) == (
        "components",
        "approved",
    )
    assert _placement(component | {"status": "blocked"}, approved) == (
        "components",
        "blocked",
    )
    pending = {"surface": "component", "call": "androidx.compose.material3.Button"}
    assert _placement(pending | {"status": "call-plan"}, approved) == (
        "components",
        "planned",
    )
    hook = {
        "surface": "hook",
        "call": "androidx.compose.material3.SliderDefaults.Thumb",
    }
    assert _placement(hook | {"status": "call-plan"}, approved) == ("hooks", "planned")
    assert _placement(hook | {"status": "blocked"}, approved) == ("hooks", "blocked")


def test_recognition_classifies_support_by_what_consumes_it() -> None:
    from tools.schema.accounting import approval_facts, recognition

    registry = _registry(
        valueTypes={
            "topAppBarColors": {
                "source": {
                    "owner": "androidx.compose.material3.TopAppBarDefaults",
                    "name": "topAppBarColors",
                    "jvmName": "topAppBarColors-5tl4gsc",
                    "descriptor": "(J)Landroidx/compose/material3/TopAppBarColors;",
                },
                "native": {
                    "call": (
                        "androidx.compose.material3.TopAppBarDefaults.topAppBarColors"
                    )
                },
            },
            "callType": {
                "source": {
                    "owner": "androidx.compose.material3.Factory",
                    "jvmName": "make",
                    "descriptor": "()V",
                },
                "native": {"call": "androidx.compose.material3.Factory.make"},
            },
            "materialIcon": {
                "source": {"owner": "androidx/compose/material/icons/Icons"},
                "native": {"propertyOwner": "androidx.compose.material.icons.Icons"},
            },
        }
    )
    candidates = [
        {
            "surface": "component",
            "status": "call-plan",
            "call": "androidx.compose.material3.Button",
            "parameters": {
                "interactionSource": {
                    "type": type_doc(
                        "androidx/compose/foundation/interaction/MutableInteractionSource"
                    )
                }
            },
            "receiver": None,
        }
    ]
    facts = approval_facts(registry, candidates)

    assert (
        recognition(_support(owner="androidx.compose.material3.Absent"), facts)
        == "unrecognized"
    )
    named = _support(
        "topAppBarColors",
        "(J)Landroidx/compose/material3/TopAppBarColors;",
        owner="androidx.compose.material3.TopAppBarDefaults",
    )
    assert recognition(named, facts) == "approved"
    by_jvm = _support("make", "()V", owner="androidx.compose.material3.Factory")
    assert recognition(by_jvm, facts) == "approved"
    scoped = _support(
        "inScope",
        receiver=type_doc("androidx/compose/foundation/layout/RowScope"),
    )
    assert recognition(scoped, facts) == "scope-member"
    held = _support(owner="androidx.compose.material.icons.Icons.Filled")
    assert recognition(held, facts) == "holder-member"
    planned = _support(
        owner="androidx.compose.foundation.interaction.MutableInteractionSource"
    )
    assert recognition(planned, facts) == "planned"
    assert (
        recognition(_support(owner="androidx.compose.material3.Unknown"), facts)
        == "unrecognized"
    )


def test_protocols_report_the_activated_host_protocols() -> None:
    from tools.schema.accounting_views import protocols as _protocols

    registry = _registry(
        actions=["increment"],
        effects=["navigate"],
        lifecycle=["resumed"],
        modifiers={"padding": {}},
        components={
            "Button": {"reshaped": {"why": "copy"}},
            "Plain": {},
            "Slider": {
                "scope": {"provides": "SliderScope"},
                "state": {"kind": "slider"},
            },
            "SnackbarHost": {"transient": {"kind": "snackbar"}},
            "Surface": {"slots": ["content"]},
        },
    )
    view = _protocols(registry)
    assert view["actions"] == ["increment"]
    assert view["effects"] == ["navigate"]
    assert view["lifecycle"] == ["resumed"]
    assert view["modifiers"] == ["padding"]
    assert view["state"] == ["Slider"]
    assert view["transient"] == ["SnackbarHost"]
    assert view["scopes"] == ["Slider"]
    assert view["slots"] == ["Surface"]
    assert view["reshaped"] == ["Button"]
    assert view["stateByKind"]["slider"] == ["Slider"]
    assert view["stateByKind"]["drawer"] == []
    assert view["transientByKind"]["snackbar"] == ["SnackbarHost"]


def test_grounding_reconciles_components_and_value_sources() -> None:
    from tools.schema.accounting_views import grounding as _grounding
    from tools.schema.classpath_dump import Declaration, Inventory

    registry = _registry(
        components={"Box": {"package": "androidx.compose.foundation.layout"}},
        valueTypes={
            "topAppBarColors": {
                "source": {
                    "owner": "androidx.compose.material3.TopAppBarDefaults",
                    "jvmName": "topAppBarColors-5tl4gsc",
                    "descriptor": "(J)Landroidx/compose/material3/TopAppBarColors;",
                }
            }
        },
    )
    plan = {
        "candidates": [
            {"call": "androidx.compose.foundation.layout.Row", "status": "call-plan"},
            {"call": "androidx.compose.material3.Slider", "status": "blocked"},
        ]
    }
    binder = Declaration.read(
        declaration(
            "topAppBarColors",
            "(J)Landroidx/compose/material3/TopAppBarColors;",
            owner="androidx.compose.material3.TopAppBarDefaults",
            disposition="support",
            composable=False,
            jvm={
                "name": "topAppBarColors-5tl4gsc",
                "descriptor": "(J)Landroidx/compose/material3/TopAppBarColors;",
                "matched": True,
            },
        )
    )
    pinned = Inventory(
        bom="b", compiler="c", declarations=(binder,), classes=(), document={}
    )
    assert _grounding(registry, plan, pinned) == {
        "ungroundedComponents": ["Box"],
        "ungroundedValues": [],
    }
    absent = Inventory(bom="b", compiler="c", declarations=(), classes=(), document={})
    assert _grounding(registry, plan, absent)["ungroundedValues"] == ["topAppBarColors"]


def test_strict_findings_refuse_incompleteness_not_coverage() -> None:
    from tools.schema.accounting import strict_findings

    assert strict_findings(_report()) == []
    unclassified = _report(domains={"material": {}, "unclassified": {}})
    assert strict_findings(unclassified) == [
        "domains: unclassified declarations present"
    ]
    reasons = _report(
        gaps={
            "classes": {},
            "unclassifiedReasons": {"new reason": 1},
            "diagnostics": [],
        }
    )
    assert strict_findings(reasons) == ["gaps: unclassified planner reasons present"]
    values = _report(
        grounding={"ungroundedComponents": [], "ungroundedValues": ["ThemeColor"]}
    )
    assert strict_findings(values) == [
        "grounding: approved value sources are not on the pin"
    ]
    target = _report(
        gaps={
            "classes": {},
            "unclassifiedReasons": {},
            "diagnostics": [{"message": "material3 gap", "target": True}],
        }
    )
    assert strict_findings(target) == ["extraction: target diagnostics present"]
    delta = _report(grounding={"ungroundedComponents": ["Box"], "ungroundedValues": []})
    assert strict_findings(delta) == []


def test_summarize_renders_every_section_deterministically() -> None:
    from tools.schema.accounting import summarize

    text = summarize(_report())
    lines = text.splitlines()
    assert lines[0] == "pin: bom 2026.09.00 compiler 2.4.21"
    assert "denominator: ui 2, support 2" in lines
    assert "plan: approved 1, planned 0, blocked 1" in lines
    assert "support: approved 2" in lines
    assert "gaps: value-binding 1" in lines
    assert (
        "grounding: unplanned approved components 0, ungrounded value sources 0"
        in lines
    )
    assert "  material: ui 2 support 2 | approved 1 planned 0 blocked 1" in lines
    assert summarize(_report()) == text


def test_account_partitions_a_synthetic_inventory(tmp_path: Path) -> None:
    from tools.schema.accounting import account, strict_findings
    from tools.schema.classpath_dump import inventory

    records = [
        declaration("Inside", "inside", owner="androidx.compose.material3.InsideKt"),
        declaration(
            "Hooked",
            "hooked",
            owner="androidx.compose.material3.HookedKt",
            dispatchReceiver=type_doc("androidx/compose/material3/Carrier"),
        ),
        declaration(
            "make",
            "()V",
            owner="androidx.compose.material3.Factory",
            disposition="support",
            composable=False,
        ),
        declaration(
            "member",
            "()V",
            owner="androidx.compose.material3.Holder",
            disposition="support",
            composable=False,
        ),
        declaration(
            "hidden",
            "hidden",
            disposition="excluded",
            reason="non-public Kotlin declaration",
            visibility="PRIVATE",
            composable=False,
        ),
        declaration(
            "size",
            "size",
            owner="androidx.navigation3.runtime.NavBackStack",
            package="androidx.navigation3.runtime",
            disposition="error",
            reason="unmatched property accessor/field",
            composable=False,
            jvm={"name": "size", "descriptor": None, "matched": False},
        ),
    ]
    write_inventory(
        tmp_path,
        records,
        diagnostics=[{"target": False, "message": "example extraction gap"}],
    )
    registry = _registry(
        components={"Inside": {"package": "androidx.compose.material3"}},
        valueTypes={
            "callType": {
                "source": {
                    "owner": "androidx.compose.material3.Factory",
                    "name": "make",
                    "jvmName": "make",
                    "descriptor": "()V",
                },
                "native": {"call": "androidx.compose.material3.Factory.make"},
            },
            "holderThing": {
                "source": {"owner": "androidx.compose.material3.Holder"},
                "native": {"propertyOwner": "androidx.compose.material3.Holder"},
            },
        },
    )
    report = account(inventory(tmp_path), {}, registry)

    assert report["denominator"] == {
        "declarations": 6,
        "dispositions": {"error": 1, "excluded": 1, "support": 2, "ui": 2},
        "excludedReasons": {"non-public Kotlin declaration": 1},
        "requiredSupport": 0,
    }
    material = report["domains"]["material"]
    assert material["declarations"] == {"excluded": 1, "support": 2, "ui": 2}
    assert material["components"] == {
        "approved": ["Inside"],
        "planned": [],
        "blocked": [],
    }
    assert material["hooks"] == {"planned": [], "blocked": ["Hooked"]}
    assert material["overloads"] == {"approved": 1, "blocked": 1}
    assert material["support"] == {"approved": 1, "holder-member": 1}
    assert material["gaps"] == {"runtime-protocol": 1}
    assert report["domains"]["navigation"]["declarations"] == {"error": 1}
    assert report["supportRecognition"] == {"approved": 1, "holder-member": 1}
    assert report["grounding"] == {"ungroundedComponents": [], "ungroundedValues": []}
    assert report["gaps"]["classes"] == {"runtime-protocol": 1}
    assert report["gaps"]["extractionErrors"] == [
        {
            "artifact": "androidx.compose.material3:material3-android:1.4.0",
            "owner": "androidx.navigation3.runtime.NavBackStack",
            "name": "size",
            "message": "unmatched property accessor/field",
        }
    ]
    assert report["gaps"]["diagnostics"] == [
        {"message": "example extraction gap", "target": False}
    ]
    assert strict_findings(report) == []


def test_the_cli_refuses_to_write_over_the_approved_schema() -> None:
    from tools.schema.accounting import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--schema", "schema/components.json", "--out", "schema/components.json"])
    assert exit_info.value.code == 2


def test_the_account_is_strict_and_byte_stable_at_the_pin(native_document, tmp_path):
    from tools.schema.accounting import DOMAINS, account, main, strict_findings
    from tools.schema.classpath_dump import inventory, source_defaults

    assert native_document["provenance"]["bom"] == "2026.09.00"
    found = inventory(DUMP)
    registry = json.loads(Path("schema/components.json").read_text())
    report = account(found, source_defaults(DUMP), registry)

    out = tmp_path / "accounting.json"
    assert main(["--inventory", str(DUMP), "--out", str(out), "--strict"]) == 0
    assert out.read_text() == json.dumps(report, indent=2, ensure_ascii=False) + "\n"

    # The partition is total: every declaration in exactly one disposition and
    # every planned overload in exactly one domain bucket.
    dispositions = report["denominator"]["dispositions"]
    assert report["denominator"]["declarations"] == sum(dispositions.values())
    assert (
        sum(sum(data["declarations"].values()) for data in report["domains"].values())
        == report["denominator"]["declarations"]
    )
    assert (
        sum(sum(data["overloads"].values()) for data in report["domains"].values())
        == dispositions["ui"]
    )
    assert set(report["domains"]) <= set(DOMAINS) | {"unclassified"}

    # The strict bar is completeness, not coverage: the report names the
    # approved components the planner does not plan, while the approved value
    # sources all resolve at the pin.
    assert strict_findings(report) == []
    approved = set(registry["components"])
    assert set(report["grounding"]["ungroundedComponents"]) <= approved
    assert report["grounding"]["ungroundedValues"] == []
    assert len(report["gaps"]["extractionErrors"]) == dispositions.get("error", 0)
