# Third-party components

Copyright (c) 2026 Missher applies only to the original Media@Missher work for which
Missher holds the relevant rights. It does not replace any third-party license or
claim ownership of browser software, platform content, dependencies or user data.

Current direct runtime dependencies:

| Component | Version | Declared license | Delivery |
| --- | --- | --- | --- |
| ExcelJS | 4.4.0 | MIT | External Node dependency installed by pnpm, with its original notices |
| saxes | 5.0.1 | ISC | External Node dependency installed by pnpm, with its original notices |
| Playwright for Python | 1.45.0 | Apache-2.0 | Installed separately from the pinned runtime requirement, with its original notices |

Node dependencies are external imports in the compiled Bundle. Their transitive
dependencies are resolved from pnpm-lock.yaml and retain their own original
copyright and license files. Python package dependencies retain the license files
in their installed distributions. Nothing in Media@Missher's proprietary notice
restricts rights granted for those independently licensed components.

Google Chrome and DeepSeek Harness are separate host applications and are not
included in this Bundle. Optional BrowserSkill is not automatically installed or
bundled. Historical upstream projects are not relicensed by this notice.

Before a future public release, review the exact dependency versions, complete
transitive licenses, any required notices, host distribution terms and source
provenance for that release. This direct-dependency inventory is not a claim that
such a future distribution review has already been completed.

## Bundled TypeScript declarations

The generated `lib/index.d.ts` includes declarations from the following SDK and
schema packages. These declarations remain licensed under their original MIT
licenses; they are not relicensed as proprietary Media@Missher code. The original
license texts copied from the installed pinned package distributions follow.

- @deepseek-ai/cosmokit 1.8.2
- @deepseek-ai/cordis 4.0.1
- @deepseek-ai/schemastery 3.18.1

```text
MIT License

Copyright (c) 2021-present Shigma

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- @standard-schema/spec 1.1.0

```text
MIT License

Copyright (c) 2024 Colin McDonnell

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- @deepseek-ai/dsh-scope 0.1.1-rc.2
- @deepseek-ai/dsh-brand 0.1.1-rc.2
- @deepseek-ai/dsh-attachment 0.1.1-rc.2
- @deepseek-ai/dsh-llm 0.1.1-rc.2
- @deepseek-ai/dsh-session 0.1.1-rc.2
- @deepseek-ai/dsh-typert-protocol 0.1.1-rc.2
- @deepseek-ai/dsh-agent 0.1.1-rc.2
- @deepseek-ai/dsh-system-prompt 0.1.1-rc.2
- @deepseek-ai/dsh-tools 0.1.1-rc.2
- @deepseek-ai/dsh-code-runtime 0.1.1-rc.2

```text
MIT License

Copyright (c) 2026 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
