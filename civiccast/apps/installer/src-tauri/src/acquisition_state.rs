// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! In-memory store for component-download progress, written into by the
//! download engine's `ProgressObserver` (`component_acquisition.rs`) and
//! read by `main.rs`'s `write_installer_state` to populate the polled
//! installer-state JSON's `acquisition` field.
//!
//! The types below mirror `src/types.ts`'s `AcquisitionState` /
//! `AcquisitionComponentProgress` / `AcquisitionComponentError` /
//! `AcquisitionErrorKind` field-for-field -- the TS side is the contract
//! (see that file's own comment pointing back here). Every field name is
//! already snake_case on the Rust struct, so no `#[serde(rename_all = ...)]`
//! is needed on the structs; the two enums use
//! `#[serde(rename_all = "snake_case")]` to turn their PascalCase variants
//! into the lowercase_with_underscores string values the TS union types
//! spell out verbatim (e.g. `FoundLocally` -> `"found_locally"`).

use std::sync::Mutex;

use serde::Serialize;

/// Mirrors `AcquisitionComponentState` in `src/types.ts`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AcquisitionComponentState {
    Pending,
    FoundLocally,
    Downloading,
    Verifying,
    Complete,
    /// Stopped at the operator's request (G011.3). Deliberately its own state
    /// rather than an `Error` with a seventh error kind: nothing went wrong,
    /// no remedy needs naming, and the screen must offer Resume without any
    /// of the red failure treatment. Any `.partial` bytes are left in place,
    /// so Resume genuinely resumes.
    Canceled,
    Error,
}

/// Mirrors `AcquisitionErrorKind` in `src/types.ts`, which in turn mirrors
/// `component_acquisition::AcquisitionError`'s variants.
///
/// `DiskFull` is no longer the catch-all for local write failures (chain H2):
/// `PermissionDenied` and `WriteFailed` are their own kinds because the
/// frontend keys ALL of its operator copy off this value and nothing else, so
/// a wrong kind here is a wrong screen there.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AcquisitionErrorKind {
    NetworkFailed,
    ResumeInvalid,
    HashMismatch,
    DiskFull,
    PermissionDenied,
    WriteFailed,
    SourceNotFound,
}

/// Mirrors `AcquisitionComponentError` in `src/types.ts`. `detail` is the
/// raw engine detail string -- the TS side's own comment notes it is never
/// shown verbatim on screen (the frontend presents copy keyed off `kind`
/// only), so no attempt is made here to make `detail` end-user-friendly.
#[derive(Debug, Clone, Serialize)]
pub struct AcquisitionComponentError {
    pub kind: AcquisitionErrorKind,
    pub detail: String,
}

/// Mirrors `AcquisitionComponentProgress` in `src/types.ts`.
#[derive(Debug, Clone, Serialize)]
pub struct AcquisitionComponentProgress {
    pub id: String,
    pub state: AcquisitionComponentState,
    pub bytes_done: u64,
    pub bytes_total: Option<u64>,
    pub elapsed_seconds: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<AcquisitionComponentError>,
}

/// Mirrors `AcquisitionState` in `src/types.ts`.
#[derive(Debug, Clone, Serialize)]
pub struct AcquisitionState {
    pub components: Vec<AcquisitionComponentProgress>,
}

// ---------------------------------------------------------------------------
// Pure helpers, operating on a caller-supplied `Vec` -- kept separate from
// the global store below so unit tests never share state across parallel
// `cargo test` threads (a single process-wide `static` would make tests
// interfere with each other).
// ---------------------------------------------------------------------------

/// Insert or replace (by `id`) one component's progress.
pub fn upsert_into(components: &mut Vec<AcquisitionComponentProgress>, progress: AcquisitionComponentProgress) {
    if let Some(existing) = components.iter_mut().find(|candidate| candidate.id == progress.id) {
        *existing = progress;
    } else {
        components.push(progress);
    }
}

/// Reset one component back to `pending`: zeroed bytes/elapsed, no error.
/// `bytes_total` is intentionally preserved from any existing entry (a
/// retried component's known size does not change) rather than cleared.
pub fn mark_pending_in(components: &mut Vec<AcquisitionComponentProgress>, component_id: &str) {
    if let Some(existing) = components.iter_mut().find(|candidate| candidate.id == component_id) {
        existing.state = AcquisitionComponentState::Pending;
        existing.bytes_done = 0;
        existing.elapsed_seconds = 0;
        existing.error = None;
    } else {
        components.push(AcquisitionComponentProgress {
            id: component_id.to_string(),
            state: AcquisitionComponentState::Pending,
            bytes_done: 0,
            bytes_total: None,
            elapsed_seconds: 0,
            error: None,
        });
    }
}

/// Mark every component that has NOT already finished as `Canceled`,
/// clearing any error (a stop the operator asked for supersedes whatever the
/// row was doing, including a failure it was about to be retried from).
/// `bytes_done`/`bytes_total` are preserved: the `.partial` on disk really
/// does hold those bytes, and Resume will continue from them.
pub fn mark_unfinished_canceled_in(components: &mut [AcquisitionComponentProgress]) {
    for component in components.iter_mut() {
        if matches!(
            component.state,
            AcquisitionComponentState::Complete | AcquisitionComponentState::FoundLocally
        ) {
            continue;
        }
        component.state = AcquisitionComponentState::Canceled;
        component.error = None;
    }
}

/// Serialize `components` into the `acquisition` field's JSON value, or
/// `None` when there is nothing to report -- matching `InstallerProgress
/// .acquisition`'s documented meaning in `src/types.ts`: "its absence means
/// 'no acquisition activity to report', not an error."
pub fn state_json_from(components: &[AcquisitionComponentProgress]) -> Option<String> {
    if components.is_empty() {
        return None;
    }
    serde_json::to_string(&AcquisitionState {
        components: components.to_vec(),
    })
    .ok()
}

// ---------------------------------------------------------------------------
// Global store: the seam the Tauri layer (main.rs) actually uses. A poisoned
// lock (a panic while holding it) is recovered from rather than propagated --
// losing one update's worth of progress is far preferable to a poisoned
// Mutex permanently breaking every later installer-state write.
// ---------------------------------------------------------------------------

static ACQUISITION_STORE: Mutex<Vec<AcquisitionComponentProgress>> = Mutex::new(Vec::new());

/// Insert or replace one component's progress in the global store.
pub fn upsert(progress: AcquisitionComponentProgress) {
    let mut store = ACQUISITION_STORE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    upsert_into(&mut store, progress);
}

/// Reset one component back to `pending` in the global store.
pub fn mark_pending(component_id: &str) {
    let mut store = ACQUISITION_STORE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    mark_pending_in(&mut store, component_id);
}

/// [`mark_unfinished_canceled_in`] against the global store.
pub fn mark_unfinished_canceled() {
    let mut store = ACQUISITION_STORE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    mark_unfinished_canceled_in(&mut store);
}

/// The global store's current snapshot, serialized -- what `write_installer_state`
/// splices into the polled installer-state JSON's `acquisition` field.
pub fn snapshot_json() -> Option<String> {
    let store = ACQUISITION_STORE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    state_json_from(&store)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn upsert_into_adds_a_new_component() {
        let mut components = Vec::new();
        upsert_into(
            &mut components,
            AcquisitionComponentProgress {
                id: "app_runtime".to_string(),
                state: AcquisitionComponentState::Downloading,
                bytes_done: 10,
                bytes_total: Some(100),
                elapsed_seconds: 1,
                error: None,
            },
        );
        assert_eq!(components.len(), 1);
        assert_eq!(components[0].id, "app_runtime");
    }

    #[test]
    fn upsert_into_replaces_an_existing_component_by_id_without_duplicating() {
        let mut components = vec![AcquisitionComponentProgress {
            id: "app_runtime".to_string(),
            state: AcquisitionComponentState::Downloading,
            bytes_done: 10,
            bytes_total: Some(100),
            elapsed_seconds: 1,
            error: None,
        }];
        upsert_into(
            &mut components,
            AcquisitionComponentProgress {
                id: "app_runtime".to_string(),
                state: AcquisitionComponentState::Complete,
                bytes_done: 100,
                bytes_total: Some(100),
                elapsed_seconds: 9,
                error: None,
            },
        );
        assert_eq!(components.len(), 1);
        assert_eq!(components[0].state, AcquisitionComponentState::Complete);
        assert_eq!(components[0].bytes_done, 100);
    }

    #[test]
    fn mark_pending_in_resets_progress_and_error_but_preserves_bytes_total() {
        let mut components = vec![AcquisitionComponentProgress {
            id: "captions_medium".to_string(),
            state: AcquisitionComponentState::Error,
            bytes_done: 4096,
            bytes_total: Some(1_500_000_000),
            elapsed_seconds: 30,
            error: Some(AcquisitionComponentError {
                kind: AcquisitionErrorKind::NetworkFailed,
                detail: "connection reset".to_string(),
            }),
        }];
        mark_pending_in(&mut components, "captions_medium");
        assert_eq!(components.len(), 1);
        let component = &components[0];
        assert_eq!(component.state, AcquisitionComponentState::Pending);
        assert_eq!(component.bytes_done, 0);
        assert_eq!(component.elapsed_seconds, 0);
        assert!(component.error.is_none());
        assert_eq!(component.bytes_total, Some(1_500_000_000));
    }

    #[test]
    fn mark_pending_in_creates_a_fresh_pending_entry_for_an_unknown_component() {
        let mut components = Vec::new();
        mark_pending_in(&mut components, "local_ai_model");
        assert_eq!(components.len(), 1);
        assert_eq!(components[0].id, "local_ai_model");
        assert_eq!(components[0].state, AcquisitionComponentState::Pending);
        assert_eq!(components[0].bytes_total, None);
    }

    #[test]
    fn state_json_from_is_none_for_an_empty_component_list() {
        assert_eq!(state_json_from(&[]), None);
    }

    #[test]
    fn state_json_from_matches_the_types_ts_contract_shape_exactly() {
        let components = vec![AcquisitionComponentProgress {
            id: "captions_medium".to_string(),
            state: AcquisitionComponentState::Downloading,
            bytes_done: 512,
            bytes_total: Some(1024),
            elapsed_seconds: 3,
            error: None,
        }];
        let json = state_json_from(&components).expect("non-empty state serializes");
        assert_eq!(
            json,
            "{\"components\":[{\"id\":\"captions_medium\",\"state\":\"downloading\",\"bytes_done\":512,\"bytes_total\":1024,\"elapsed_seconds\":3}]}"
        );
    }

    #[test]
    fn state_json_from_includes_the_typed_error_with_snake_case_kind() {
        let components = vec![AcquisitionComponentProgress {
            id: "server_binaries".to_string(),
            state: AcquisitionComponentState::Error,
            bytes_done: 0,
            bytes_total: None,
            elapsed_seconds: 0,
            error: Some(AcquisitionComponentError {
                kind: AcquisitionErrorKind::SourceNotFound,
                detail: "https://example.invalid/asset.ccpack".to_string(),
            }),
        }];
        let json = state_json_from(&components).expect("non-empty state serializes");
        assert_eq!(
            json,
            "{\"components\":[{\"id\":\"server_binaries\",\"state\":\"error\",\"bytes_done\":0,\"bytes_total\":null,\"elapsed_seconds\":0,\"error\":{\"kind\":\"source_not_found\",\"detail\":\"https://example.invalid/asset.ccpack\"}}]}"
        );
    }

    #[test]
    fn every_error_kind_serializes_to_the_pinned_snake_case_strings() {
        let cases = [
            (AcquisitionErrorKind::NetworkFailed, "\"network_failed\""),
            (AcquisitionErrorKind::ResumeInvalid, "\"resume_invalid\""),
            (AcquisitionErrorKind::HashMismatch, "\"hash_mismatch\""),
            (AcquisitionErrorKind::DiskFull, "\"disk_full\""),
            (AcquisitionErrorKind::PermissionDenied, "\"permission_denied\""),
            (AcquisitionErrorKind::WriteFailed, "\"write_failed\""),
            (AcquisitionErrorKind::SourceNotFound, "\"source_not_found\""),
        ];
        for (kind, expected) in cases {
            assert_eq!(serde_json::to_string(&kind).expect("serialize kind"), expected);
        }
    }

    #[test]
    fn all_seven_component_states_serialize_to_the_pinned_snake_case_strings() {
        let cases = [
            (AcquisitionComponentState::Pending, "\"pending\""),
            (AcquisitionComponentState::FoundLocally, "\"found_locally\""),
            (AcquisitionComponentState::Downloading, "\"downloading\""),
            (AcquisitionComponentState::Verifying, "\"verifying\""),
            (AcquisitionComponentState::Complete, "\"complete\""),
            (AcquisitionComponentState::Canceled, "\"canceled\""),
            (AcquisitionComponentState::Error, "\"error\""),
        ];
        for (state, expected) in cases {
            assert_eq!(serde_json::to_string(&state).expect("serialize state"), expected);
        }
    }

    #[test]
    fn mark_unfinished_canceled_in_stops_the_unfinished_and_leaves_the_finished_alone() {
        let mut components = vec![
            AcquisitionComponentProgress {
                id: "app_runtime".to_string(),
                state: AcquisitionComponentState::Complete,
                bytes_done: 100,
                bytes_total: Some(100),
                elapsed_seconds: 9,
                error: None,
            },
            AcquisitionComponentProgress {
                id: "captions_medium".to_string(),
                state: AcquisitionComponentState::Downloading,
                bytes_done: 40,
                bytes_total: Some(100),
                elapsed_seconds: 3,
                error: None,
            },
            AcquisitionComponentProgress {
                id: "local_ai_model".to_string(),
                state: AcquisitionComponentState::Error,
                bytes_done: 0,
                bytes_total: Some(100),
                elapsed_seconds: 1,
                error: Some(AcquisitionComponentError {
                    kind: AcquisitionErrorKind::NetworkFailed,
                    detail: "connection reset".to_string(),
                }),
            },
        ];
        mark_unfinished_canceled_in(&mut components);

        assert_eq!(components[0].state, AcquisitionComponentState::Complete);
        assert_eq!(components[1].state, AcquisitionComponentState::Canceled);
        // The partially-downloaded bytes are preserved -- the `.partial` on
        // disk really does hold them, and Resume continues from there.
        assert_eq!(components[1].bytes_done, 40);
        assert_eq!(components[2].state, AcquisitionComponentState::Canceled);
        assert!(
            components[2].error.is_none(),
            "a stop the operator asked for supersedes the failure the row was showing"
        );
    }

    #[test]
    fn mark_unfinished_canceled_in_leaves_a_found_locally_component_alone() {
        let mut components = vec![AcquisitionComponentProgress {
            id: "server_binaries".to_string(),
            state: AcquisitionComponentState::FoundLocally,
            bytes_done: 100,
            bytes_total: Some(100),
            elapsed_seconds: 0,
            error: None,
        }];
        mark_unfinished_canceled_in(&mut components);
        assert_eq!(components[0].state, AcquisitionComponentState::FoundLocally);
    }

    // -----------------------------------------------------------------
    // Global store: exercised through the public `upsert`/`mark_pending`/
    // `snapshot_json` API with a unique component id per test (rather than
    // asserting the WHOLE store's contents) so these remain correct even
    // though `cargo test` runs test functions across threads in the same
    // process and this `static` is shared crate-wide.
    // -----------------------------------------------------------------

    #[test]
    fn global_store_upsert_and_snapshot_round_trip_a_unique_component() {
        let unique_id = "test-only-global-store-round-trip";
        upsert(AcquisitionComponentProgress {
            id: unique_id.to_string(),
            state: AcquisitionComponentState::Downloading,
            bytes_done: 7,
            bytes_total: Some(70),
            elapsed_seconds: 1,
            error: None,
        });
        let json = snapshot_json().expect("global store is non-empty once anything has run");
        assert!(json.contains(unique_id));
        assert!(json.contains("\"bytes_done\":7"));

        mark_pending(unique_id);
        let json_after_reset = snapshot_json().expect("still non-empty");
        assert!(json_after_reset.contains(&format!("\"id\":\"{unique_id}\",\"state\":\"pending\",\"bytes_done\":0")));
    }
}
