# Publish the reconstructed history to GitHub

## 1. Configure your Git identity

Use the name and email you want GitHub to associate with the reconstructed commits:

```bash
git config --global user.name "Your Name"
git config --global user.email "your-github-associated-email@example.com"
```

If you use GitHub's private-email option, use the noreply address shown in your GitHub email settings.

## 2. Reconstruct the repository

Keep these three files in the same working directory:

- `job_search_agent_v1_3 to v1_8_3.zip`
- `job_search_agent_v1_9_0.zip`
- `job_search_agent_public_ready.zip`

Then run:

```bash
python reconstruct_public_job_agent_history.py \
  --archive-bundle "job_search_agent_v1_3 to v1_8_3.zip" \
  --v190-zip job_search_agent_v1_9_0.zip \
  --public-overlay job_search_agent_public_ready.zip \
  --output job-search-agent
```

On Windows PowerShell, the same command can be entered on one line.

The script runs the test suite before completing. Use `--skip-tests` only if you intentionally want to bypass that verification.

## 3. Inspect the result

```bash
cd job-search-agent
git status
git log --graph --decorate --oneline --all
git tag --list "v*" --sort=version:refname
```

Expected result:

- 13 version-tagged reconstructed snapshot commits;
- one final public-presentation commit after `v1.9.0`;
- a clean working tree;
- no fabricated tags for `v1.7.1` or `v1.8.2-hotfix1`.

## 4. Create an empty GitHub repository

Create a new repository on GitHub without initializing it with a README, `.gitignore`, or license. Keeping it empty avoids an unnecessary merge before the reconstructed history is pushed.

## 5. Push main and tags

Replace the remote URL with your repository URL:

```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
git push -u origin main
git push origin --tags
```

Do not force-push unless you intentionally need to replace an existing remote history.

## 6. Final GitHub checks

After the push:

- confirm the README renders the Mermaid architecture diagram;
- confirm the synthetic dashboard image is visible;
- open the Actions tab and verify the test workflow passes;
- inspect several tags to confirm the release progression is readable;
- confirm no personal `.env`, runtime database, generated application package, or raw email-alert file was committed;
- choose a license only when you are comfortable granting those reuse rights.
