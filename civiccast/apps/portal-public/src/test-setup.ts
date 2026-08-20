// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Global vitest setup for the public portal — mirrors the operator portal's
// pattern (registers testing-library's DOM cleanup after every test so renders
// never leak into the next test's document.body).
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(cleanup)
