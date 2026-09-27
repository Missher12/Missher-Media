# Understand the licensing boundary

This repository contains an independently authored runtime, two compact skill packages, a standard-library adapter, and synthetic tests. The installable skills contain no copied platform implementation, dependency environment, browser asset, collected data, or inherited source header.

Historical upstream components remain governed by their own license files and restrictions. They are not dependencies of the shared runtime, and this repository does not copy, distribute, or relicense them.

On 2026-09-07 the owner selected a proprietary notice for the original work: Copyright (c) 2026 Missher, all rights reserved. See the repository LICENSE, COPYRIGHT.md and THIRD_PARTY_NOTICES.md. Unauthorized modification, derivative versions and redistribution are prohibited within the stated scope and applicable exceptions. This does not relicense third-party components or cancel previously granted rights. Owner-authorized maintenance remains permitted.

The V15 repository and any GitHub destination must remain private. A private GitHub backup or review does not authorize public distribution, release artifacts, screenshots, browser traces, profiles, cookies, runtime state, or collected data. Public GitHub publication remains blocked until the same license and provenance review is complete.

An upgrade keeps private `previous-{release_timestamp}` components for recovery. A destructive cutover can move replaced components to exact Trash destinations recorded in private handoff evidence. Neither recovery path changes ownership or licensing.

Rollback restores matching prior runtime and skill releases. It does not delete current-run evidence, rewrite historical records, or authorize a remote Feishu write.
