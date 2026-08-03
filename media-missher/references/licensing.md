# Understand the licensing boundary

This repository contains an independently authored runtime, two compact skill packages, a standard-library adapter, and synthetic tests. The installable skills contain no copied platform implementation, dependency environment, browser asset, collected data, or inherited source header.

Historical upstream components remain governed by their own license files and restrictions. They are not dependencies of the shared runtime, and this repository does not copy, distribute, or relicense them.

No repository-wide license has been selected. Do not add one, publish a combined bundle, or copy historical upstream code until the owner selects a license and a provenance review confirms that every component can be distributed under compatible terms.

An upgrade keeps private `previous-{release_timestamp}` components for recovery. A destructive cutover can move replaced components to exact Trash destinations recorded in private handoff evidence. Neither recovery path changes ownership or licensing.

Rollback restores matching prior runtime and skill releases. It does not delete current-run evidence, rewrite historical records, or authorize a remote Feishu write.
