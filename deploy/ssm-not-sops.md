# Why SSM Parameter Store, not SOPS

November 23, 2026

For Serena and the BMU, we keep deployment settings in AWS Systems Manager Parameter Store, as **one document per
environment** that Ops edits in the AWS console, and keep secrets in Secrets Manager. That gives Ops what they asked
SOPS for (one place to see and edit everything), without putting encrypted secrets in our public repositories or
passing them through the deploy pipeline.

## What Ops wanted, and how they get it

Ops asked for SOPS so they could see and edit an environment's settings in one file. Mostly they wanted easier
editing, and to a lesser degree history and review. The settings document gives all of these.

| Ops wanted | With SOPS | With the SSM settings document |
| --- | --- | --- |
| One place | One encrypted file per environment, in git | One parameter per environment, such as `/bmu-qa/settings/all`, one `NAME="value"` line per setting |
| Edit several values at once | Decrypt into an editor, then commit | Edit the text in the console (Parameter Store › Edit) and save. Comments stay. |
| History | Git history | Every version in the console's History tab; CloudTrail records who saved each one |
| Review | A pull request | Changes take effect only through a pipeline run, whose plan a second person reads and approves |
| Catching mistakes | Found when the file is applied | A typo, an unknown or repeated setting, or an unsafe character stops the pipeline's plan before Terraform, naming the line |

## Why SOPS doesn't fit here

SOPS keeps a config file in git with its keys readable and each value encrypted with a KMS key. It's a good tool, but
it conflicts with three deliberate choices in Serena and the BMU.

1. **The repositories are public.** An encrypted secret, once committed, stays in git history for good. If the KMS
   key's policy is ever too loose, or the key is compromised years from now, every secret in that history is exposed
   and can't be removed. SOPS also writes the key's ARN, which contains the AWS account number, into the file, and we
   keep account numbers out of the public repositories.
2. **Secrets would pass through the pipeline.** Today no secret value goes through a deploy: the pipeline's build role
   is explicitly denied reading or setting secrets, and an admin sets each one directly. With SOPS, the pipeline would
   have to decrypt the file to apply it, so the build would need `kms:Decrypt` on the secrets, and that boundary would
   go.
3. **It would duplicate Secrets Manager.** Secrets Manager already lets the ETL server read its token through a
   resource policy, applies a password change in minutes without a deploy, keeps the previous value working during a
   rotation, and logs every read in CloudTrail. SOPS would still have to load the values into Secrets Manager, leaving
   two copies to keep in step.

SOPS could make sense for settings kept in a *private* repository, if Ops later wants pull-request review. That
removes the first objection. The second and third still apply to secrets, so secrets would stay in Secrets Manager
either way.

## Security benefits of SSM for code in GitHub

Keeping configuration in SSM, outside the repository, is the safer default for any GitHub repository, public or
private.

- **Nothing to leak from git.** No value, encrypted or not, is in the repository, its forks, its clones or public
  archives, so no future key mistake can expose past values.
- **Access is controlled and logged.** Reading a value takes IAM permission in the AWS account, and CloudTrail records
  each read and each change. Nobody can tell who has read a git repository.
- **Less for an attacker to learn.** Setting names, account numbers and key ARNs stay out of the repository.
- **Mistakes stay contained.** There's no decrypted file to commit by accident, and no exposed secret to rotate
  because someone did.
- **Rotation is simple.** Changing a value in SSM replaces it. With SOPS, the old encrypted values stay in git
  history, so after any doubt every secret ever stored there has to be changed.
- **Least privilege is easy.** IAM can limit each role to the parameters it needs, as Serena's pipeline is limited to
  reading its settings. Anyone who can decrypt a SOPS file sees everything in it.

How Serena keeps its settings in SSM: [Settings in SSM Parameter Store](README.md#settings-in-ssm-parameter-store),
in `deploy/README.md`. The BMU's, the same design:
[Settings in SSM Parameter Store](https://github.com/ets-berkeley-edu/cspace-bulk-media-uploader/blob/main/deploy/README.md#settings-in-ssm-parameter-store)
in its `deploy/README.md`.
