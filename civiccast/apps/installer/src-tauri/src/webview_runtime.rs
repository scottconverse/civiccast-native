// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

use std::path::{Path, PathBuf};

/// Existing evergreen files can be usable even when default registration
/// lookup fails. Only use Microsoft runtime folders accepted by the loader.
pub fn usable_runtime_folder(
    roots: &[PathBuf],
    mut usable: impl FnMut(&Path) -> bool,
) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    for root in roots {
        let Ok(entries) = std::fs::read_dir(root) else {
            continue;
        };
        for entry in entries.flatten() {
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            let Ok(version) = name
                .split('.')
                .map(str::parse::<u32>)
                .collect::<Result<Vec<_>, _>>()
            else {
                continue;
            };
            if version.len() == 4 && entry.path().join("msedgewebview2.exe").is_file() {
                candidates.push((version, entry.path()));
            }
        }
    }
    candidates.sort_by(|a, b| b.0.cmp(&a.0));
    candidates
        .into_iter()
        .map(|(_, path)| path)
        .find(|path| usable(path))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chooses_highest_loader_usable_runtime_and_ignores_nonversion_folders() {
        let root =
            std::env::temp_dir().join(format!("civiccast-webview-test-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        for version in [
            "154.0.4258.62",
            "154.0.4258.9",
            "155.0.0.0",
            "not-a-version",
        ] {
            let dir = root.join(version);
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(dir.join("msedgewebview2.exe"), b"test fixture").unwrap();
        }
        let mut checked = Vec::new();
        let selected = usable_runtime_folder(&[root.clone()], |path| {
            checked.push(path.file_name().unwrap().to_string_lossy().to_string());
            path.ends_with("154.0.4258.62")
        });
        assert_eq!(selected, Some(root.join("154.0.4258.62")));
        assert_eq!(checked, ["155.0.0.0", "154.0.4258.62"]);
        assert_eq!(usable_runtime_folder(&[root.clone()], |_| false), None);
        std::fs::remove_dir_all(root).unwrap();
    }
}
