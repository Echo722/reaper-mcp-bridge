# Releasing

Users install straight from this GitHub repository
(`uvx --from git+https://github.com/Echo722/reaper-mcp-bridge ...`), so a
release is just a push to `main`. Nothing is uploaded to PyPI.

## Per release

1. Bump `version` in `pyproject.toml`.
2. Run the checks:
   ```sh
   uv run --with pytest pytest                      # unit tests (no REAPER needed)
   uvx --refresh --from . reaper-mcp-bridge doctor  # build and run the working tree
   ```
3. Commit and push to `main`.
4. Optional: tag the release so users can pin it:
   ```sh
   git tag v<version> && git push origin v<version>
   ```
   The pinned install source is then
   `git+https://github.com/Echo722/reaper-mcp-bridge@v<version>`.

Existing users pick up the new version with the refresh command in the
README's "Updating" section.
