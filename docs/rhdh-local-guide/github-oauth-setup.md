# GitHub OAuth Authentication Setup

This guide covers setting up GitHub OAuth authentication in RHDH Local using a GitHub OAuth App and a personal access token. This is a simpler alternative to the full [GitHub App approach](github-auth.md) — ideal for local development and demos.

## What You Get

- Sign in to RHDH with your GitHub account (instead of Guest)
- Your GitHub profile picture and display name shown in the RHDH UI
- GitHub integration for catalog discovery, templates, and plugins that need repo access

## Prerequisites

- RHDH Local running ([Getting Started Guide](getting-started.md))
- A GitHub account
- A GitHub personal access token (`GITHUB_TOKEN`)

---

## Step 1: Create a GitHub OAuth App

1. Go to **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App**
2. Fill in:

| Field | Value |
|-------|-------|
| **Application name** | `RHDH Local` |
| **Homepage URL** | `http://localhost:7007` |
| **Authorization callback URL** | `http://localhost:7007/api/auth/github/handler/frame` |

3. Click **Register application**
4. Copy the **Client ID**
5. Click **Generate a new client secret** and copy it immediately

---

## Step 2: Set Environment Variables

Add your credentials to a `.env` file in the project root (this file is gitignored):

```bash
# GitHub OAuth App credentials
AUTH_GITHUB_CLIENT_ID=your-client-id-here
AUTH_GITHUB_CLIENT_SECRET=your-client-secret-here

# Personal access token for GitHub API integration
GITHUB_TOKEN=ghp_your-token-here
```

You can generate a personal access token at **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)** with `repo` and `read:org` scopes.

---

## Step 3: Configure Authentication

Create or edit `configs/app-config/app-config.local.yaml`:

```yaml
auth:
  providers:
    github:
      development:
        clientId: ${AUTH_GITHUB_CLIENT_ID}
        clientSecret: ${AUTH_GITHUB_CLIENT_SECRET}
        signIn:
          resolvers:
          - resolver: usernameMatchingUserEntityName
            dangerouslyAllowSignInWithoutUserInCatalog: true
integrations:
  github:
  - host: github.com
    token: ${GITHUB_TOKEN}
```

### What each part does

- **`auth.providers.github`** — enables the "Sign in with GitHub" button on the login page
- **`signIn.resolvers`** — maps your GitHub username to a Backstage User entity. The `dangerouslyAllowSignInWithoutUserInCatalog: true` flag lets you sign in even if no matching User entity exists yet (useful for initial setup)
- **`integrations.github`** — gives RHDH read access to GitHub repos for catalog discovery, TechDocs, and plugins like GitHub Actions

---

## Step 4: Add Your User Entity with Profile Picture

By default, RHDH shows a generic initial (e.g., "P") as your avatar. To display your actual GitHub profile picture, create a User entity that matches your GitHub username.

Create `configs/catalog-entities/users.override.yaml`:

```yaml
apiVersion: backstage.io/v1alpha1
kind: User
metadata:
  name: your-github-username    # must match your GitHub login exactly (lowercase)
spec:
  profile:
    displayName: Your Name
    email: you@example.com
    picture: https://avatars.githubusercontent.com/u/YOUR_USER_ID?v=4
  memberOf: [rhdh-team]

---

apiVersion: backstage.io/v1alpha1
kind: Group
metadata:
  name: rhdh-team
  title: RHDH team
spec:
  type: team
  children: []
```

To find your GitHub avatar URL:

```bash
gh api user --jq '.avatar_url'
```

Then add a catalog location for this file in `app-config.local.yaml`:

```yaml
catalog:
  locations:
  - type: file
    target: /opt/app-root/src/configs/catalog-entities/users.override.yaml
    rules:
    - allow: [User, Group]
```

### Allow GitHub avatar images (CSP)

RHDH's Content Security Policy blocks external images by default. Add `avatars.githubusercontent.com` to the allowed sources in `app-config.local.yaml`:

```yaml
backend:
  csp:
    img-src:
    - "'self'"
    - "data:"
    - "https://quay.io"
    - "https://*.quay.io"
    - "https://avatars.githubusercontent.com"
```

---

## Step 5: Restart and Sign In

```bash
# Stop and start RHDH to pick up all config changes
podman stop rhdh && podman start rhdh-plugins-installer && podman start rhdh

# Or with Docker
docker stop rhdh && docker start rhdh-plugins-installer && docker start rhdh
```

Wait ~15 seconds for RHDH to start, then:

1. Open [http://localhost:7007](http://localhost:7007)
2. Click **Sign in with GitHub**
3. Authorize the OAuth App
4. Your profile picture and name should appear in the top-right corner

---

## Complete `app-config.local.yaml` Reference

Here's the full file with all sections combined:

```yaml
auth:
  providers:
    github:
      development:
        clientId: ${AUTH_GITHUB_CLIENT_ID}
        clientSecret: ${AUTH_GITHUB_CLIENT_SECRET}
        signIn:
          resolvers:
          - resolver: usernameMatchingUserEntityName
            dangerouslyAllowSignInWithoutUserInCatalog: true
integrations:
  github:
  - host: github.com
    token: ${GITHUB_TOKEN}
backend:
  csp:
    img-src:
    - "'self'"
    - "data:"
    - "https://quay.io"
    - "https://*.quay.io"
    - "https://avatars.githubusercontent.com"
catalog:
  locations:
  - type: file
    target: /opt/app-root/src/configs/catalog-entities/users.override.yaml
    rules:
    - allow: [User, Group]
techdocs:
  builder: local
  generator:
    runIn: local
  publisher:
    type: local
```

---

## Troubleshooting

### Still seeing the initial letter instead of profile picture

- Verify the `name` in `users.override.yaml` matches your GitHub username exactly (case-sensitive)
- Check that the `picture` URL is correct: `gh api user --jq '.avatar_url'`
- Confirm the CSP `img-src` includes `https://avatars.githubusercontent.com`
- Try signing out and back in — the profile is resolved at sign-in time

### "Sign in with GitHub" button not appearing

- Make sure Guest auth is not overriding GitHub auth. The base `app-config.yaml` enables Guest — your `app-config.local.yaml` adds GitHub alongside it. Both buttons should appear.

### OAuth callback error

- Verify the callback URL is exactly `http://localhost:7007/api/auth/github/handler/frame`
- Check that `AUTH_GITHUB_CLIENT_ID` and `AUTH_GITHUB_CLIENT_SECRET` are set in your `.env` file
- Look at logs: `podman compose logs rhdh | grep -i auth`
