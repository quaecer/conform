# Conform

Run an implementation against a directory of JSON cases. Each case lives
in a subdirectory with `case.json`, `input.json` and `expected.json`.
The metadata contains `id` (the directory name), `description`,
`requirements` (linked IDs) and `comparison`.

```sh
conform run --suite suite --impl 'my-tool serve-process' --report checks.ttl
```

The runner starts the supplied command once per case, writes the request
to standard input and reads a single JSON response from standard output.
Use trusted local commands. The command runs with the caller's permissions
and environment. The timeout applies to the started process.

- `canonical-equal` compares JSON values with unordered object members and
  ordered arrays. Booleans are distinct from numbers.
- `subset` permits extra members in objects. Arrays compare as whole values.
- `set-equal-on:<pointer>` compares the single referenced array as a set and
  keeps the rest of the response exact. The pointer uses RFC 6901.

The runner writes EARL to a new report and a JSON summary to standard
output. A different response is `failed`. Invalid output, failure to start,
nonzero process exit and timeout are `cantTell`. Any non-passing case
makes the run exit nonzero. Malformed suites are refused before execution.

Apache-2.0.

Copyright 2026 Mariia Steeghs-Turchina
