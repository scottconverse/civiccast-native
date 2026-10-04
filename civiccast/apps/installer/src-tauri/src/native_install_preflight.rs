// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

//! Read-only, silent admission before NSIS replaces any installed application.
//! Mirrors native.upgrade.routing's known-version ordering, including its
//! deliberately open policy for unknown version strings. No old runtime needed.

use std::cmp::Ordering;

const FLAG: &str = "--civiccast-install-version-preflight";
const INVALID_ARGUMENTS: i32 = 64;

#[derive(Debug)]
struct VersionKey<'a> {
    core: [&'a str; 3],
    pre: Option<(&'a str, &'a str)>,
}

fn digits(value: &str) -> bool {
    !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit())
}

fn version_key(value: &str) -> Option<VersionKey<'_>> {
    let mut parts = value.trim().split('-');
    let core: [&str; 3] = parts
        .next()?
        .split('.')
        .collect::<Vec<_>>()
        .try_into()
        .ok()?;
    if !core.iter().all(|part| digits(part)) {
        return None;
    }
    let pre = if let Some(pre) = parts.next() {
        let label_len = pre
            .bytes()
            .take_while(|byte| byte.is_ascii_alphabetic())
            .count();
        let (label, number) = pre.split_at(label_len);
        let number = number.strip_prefix('.').unwrap_or(number);
        if label.is_empty() || !digits(number) {
            return None;
        }
        Some((label, number))
    } else {
        None
    };
    if parts.next().is_some() {
        return None;
    }
    Some(VersionKey { core, pre })
}

// Decimal-string comparison avoids a new integer-overflow admission hole:
// Python's existing comparator accepts arbitrarily large version numbers.
fn numeric_cmp(left: &str, right: &str) -> Ordering {
    let left = left.trim_start_matches('0');
    let right = right.trim_start_matches('0');
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

fn compare(left: &VersionKey<'_>, right: &VersionKey<'_>) -> Ordering {
    for (left, right) in left.core.iter().zip(right.core.iter()) {
        let order = numeric_cmp(left, right);
        if order != Ordering::Equal {
            return order;
        }
    }
    match (left.pre, right.pre) {
        (None, None) => Ordering::Equal,
        (None, Some(_)) => Ordering::Greater,
        (Some(_), None) => Ordering::Less,
        (Some((left_label, left_number)), Some((right_label, right_number))) => left_label
            .cmp(right_label)
            .then_with(|| numeric_cmp(left_number, right_number)),
    }
}

fn is_downgrade(old: &str, new: &str) -> bool {
    match (version_key(old), version_key(new)) {
        (Some(old), Some(new)) => compare(&new, &old) == Ordering::Less,
        _ => false,
    }
}

/// Exact closed argument shape. A mixed maintenance/first-entry invocation must
/// terminate here, not fall through into either the GUI or a privileged action.
/// Candidate identity is bound to this executable, not caller-selected.
pub fn exit_code(args: &[String], candidate_version: &str) -> Option<i32> {
    if !args.iter().any(|argument| argument == FLAG) {
        return None;
    }
    if args.len() != 5
        || args[0] != FLAG
        || args[1] != "--installed-version"
        || args[3] != "--candidate-version"
        || args[4] != candidate_version
        || args[2].starts_with("--")
        || args[2].chars().any(char::is_control)
    {
        return Some(INVALID_ARGUMENTS);
    }
    Some(if is_downgrade(&args[2], candidate_version) {
        13
    } else {
        0
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn command(old: &str, candidate: &str) -> Vec<String> {
        [
            FLAG,
            "--installed-version",
            old,
            "--candidate-version",
            candidate,
        ]
        .map(String::from)
        .to_vec()
    }

    #[test]
    fn known_version_order_matches_existing_python_policy() {
        for (old, new, expected) in [
            ("1.0.0-beta.11", "1.0.0-beta.10", true),
            ("1.0.0-beta.9", "1.0.0-beta.10", false),
            ("1.0.0-beta.10", "1.0.0-beta.10", false),
            ("1.0.0-rc10", "1.0.0-rc9", true),
            ("1.0.0-rc9", "1.0.0-rc10", false),
            ("1.0.0", "1.0.0-rc10", true),
            ("1.0.0-beta.10", "1.0.0", false),
            ("1.0.0-rc1", "1.0.0-beta.99", true),
            (" 1.0.0-beta.0011 ", "1.0.0-beta.10", true),
            ("999999999999999999999999.0.0", "1.0.0-beta.10", true),
        ] {
            assert_eq!(is_downgrade(old, new), expected, "{old} -> {new}");
        }
    }

    #[test]
    fn unknown_versions_retain_existing_open_policy() {
        for old in [
            "none",
            "",
            "unknown",
            "1.0",
            "1.0.0-beta",
            "1.0.0-beta.1-extra",
        ] {
            assert!(!is_downgrade(old, "1.0.0-beta.10"));
        }
    }

    #[test]
    fn registered_newer_refuses_and_same_forward_or_unknown_allows() {
        assert_eq!(
            exit_code(&command("1.0.0-beta.11", "1.0.0-beta.10"), "1.0.0-beta.10"),
            Some(13)
        );
        for old in ["1.0.0-beta.9", "1.0.0-beta.10", "none"] {
            assert_eq!(
                exit_code(&command(old, "1.0.0-beta.10"), "1.0.0-beta.10"),
                Some(0)
            );
        }
    }

    #[test]
    fn mixed_malformed_and_candidate_substitution_never_fall_through() {
        let valid = command("1.0.0-beta.10", "1.0.0-beta.10");
        for extra in [
            "--civiccast-first-install",
            "--civiccast-stop-native-service",
            FLAG,
        ] {
            let mut mixed = valid.clone();
            mixed.push(extra.into());
            assert_eq!(exit_code(&mixed, "1.0.0-beta.10"), Some(64));
        }
        let mut missing = valid.clone();
        missing.pop();
        assert_eq!(exit_code(&missing, "1.0.0-beta.10"), Some(64));
        assert_eq!(
            exit_code(&command("none", "9.0.0"), "1.0.0-beta.10"),
            Some(64)
        );
        assert_eq!(
            exit_code(
                &command("--civiccast-first-install", "1.0.0-beta.10"),
                "1.0.0-beta.10"
            ),
            Some(64)
        );
        assert_eq!(
            exit_code(&["--civiccast-first-install".into()], "1.0.0-beta.10"),
            None
        );
    }
}
