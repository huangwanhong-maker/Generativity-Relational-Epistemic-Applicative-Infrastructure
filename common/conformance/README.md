# Implementation verification and interoperability boundary

**Class:** Verification guide  
**Status:** Experimental implementation tests; no independent cross-application conformance claim

From the programme root after setup, run the shared packages and generalized application together:

```powershell
$verificationPython = '.\applicative_infrastructure\.runtime\environments\generalized\Scripts\python.exe'
& $verificationPython -m pytest -c applicative_infrastructure/gr_generalized_application/web_application/pytest.ini applicative_infrastructure/gr_generalized_application/web_application/tests applicative_infrastructure/common/packages/gsp_record_protocol/tests applicative_infrastructure/common/packages/gsp_git_store/tests --basetemp build/gsp-tests -q
```

Set `$env:GSP_BROWSER='msedge'` to include the three browser journeys, using installed Edge. `chrome` or a separately installed Playwright Chromium can also be selected. The chosen `--basetemp` is disposable test output and must not contain runtime or other valuable files. A short workspace path avoids Git for Windows path-length restrictions in cloned test repositories.

Academia's native Python and npm checks remain separately documented in its [guide](../../gr_academia_application/README.md). The original domain protocol fixtures continue to assess that domain implementation. They do not establish a GRRP/general-protocol mapping.

Protocol fixtures remain beside the versioned package tests. This avoids duplicated authoritative copies. When an academia adapter is implemented, cross-application cases will need to exercise identity, signed-byte preservation, unmapped fields, authority, complete/partial mappings, files and failure recovery. That work is distinct from the source relocation verified here.
