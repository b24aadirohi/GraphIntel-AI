# GraphIntel AI — Container scan release gate

On 2026-09-20, Trivy scanned the complete application image, including Wolfi OS
and Python dependencies, and reported **zero HIGH and zero CRITICAL findings**.
The Python dependency audit also reported no known vulnerabilities.

Verified local image ID:

`sha256:a7bc01859bab88e1c397142f5a21a17600456cc5e162d230f2e32b1c84109bf7`

The runtime uses Wolfi with Python 3.12.14, glibc numerical runtime libraries and
timezone data. A separate build stage installs locked application dependencies;
the final image excludes uv and runs as UID/GID 10001. Package metadata remains
available to scanners. CI checks timezone lookup and numerical library execution.

Reproduce the release-severity check:

```sh
docker build -t cinegraph-ai:check .
trivy image --scanners vuln --severity HIGH,CRITICAL --exit-code 1 cinegraph-ai:check
```

No ignore list, unfixed-vulnerability exclusion or severity waiver was used.
The earlier patched Debian base had unresolved high findings and was replaced.
CI and release checks remain strict: future HIGH/CRITICAL findings block the
release. A clean scan is a dated result, not proof of the absence of vulnerabilities.
The local scan covered the host ARM64 image; other published architectures must
be validated in the release process as well.
