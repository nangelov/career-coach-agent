2026-07-11T19:49:57.7186883Z Current runner version: '2.335.1'
2026-07-11T19:49:57.7224878Z ##[group]Runner Image Provisioner
2026-07-11T19:49:57.7226215Z Hosted Compute Agent
2026-07-11T19:49:57.7227373Z Version: 20260624.560
2026-07-11T19:49:57.7228481Z Commit: 925d229a51159bc391ae97e54a2dd1fe20af789d
2026-07-11T19:49:57.7229889Z Build Date: 2026-06-24T18:26:47Z
2026-07-11T19:49:57.7231367Z Worker ID: {1593a688-0ddb-4db8-9838-ffbae15bd086}
2026-07-11T19:49:57.7232585Z Azure Region: eastus
2026-07-11T19:49:57.7233678Z ##[endgroup]
2026-07-11T19:49:57.7236148Z ##[group]Operating System
2026-07-11T19:49:57.7237410Z Ubuntu
2026-07-11T19:49:57.7238336Z 24.04.4
2026-07-11T19:49:57.7239234Z LTS
2026-07-11T19:49:57.7240587Z ##[endgroup]
2026-07-11T19:49:57.7241641Z ##[group]Runner Image
2026-07-11T19:49:57.7242831Z Image: ubuntu-24.04
2026-07-11T19:49:57.7243906Z Version: 20260705.232.1
2026-07-11T19:49:57.7246152Z Included Software: https://github.com/actions/runner-images/blob/ubuntu24/20260705.232/images/ubuntu/Ubuntu2404-Readme.md
2026-07-11T19:49:57.7248892Z Image Release: https://github.com/actions/runner-images/releases/tag/ubuntu24%2F20260705.232
2026-07-11T19:49:57.7251085Z ##[endgroup]
2026-07-11T19:49:57.7253014Z ##[group]GITHUB_TOKEN Permissions
2026-07-11T19:49:57.7256098Z Contents: read
2026-07-11T19:49:57.7257113Z Metadata: read
2026-07-11T19:49:57.7258332Z ##[endgroup]
2026-07-11T19:49:57.7261825Z Secret source: Actions
2026-07-11T19:49:57.7263289Z Prepare workflow directory
2026-07-11T19:49:57.7943644Z Prepare all required actions
2026-07-11T19:49:57.8002287Z Getting action download info
2026-07-11T19:49:57.9435919Z Download action repository 'actions/checkout@v4' (SHA:34e114876b0b11c390a56381ad16ebd13914f8d5)
2026-07-11T19:49:58.0206895Z Download action repository 'astral-sh/setup-uv@v5' (SHA:d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86)
2026-07-11T19:49:58.3347510Z Complete job name: backend
2026-07-11T19:49:58.3879113Z ##[group]Checking docker version
2026-07-11T19:49:58.3892384Z ##[command]/usr/bin/docker version --format '{{.Server.APIVersion}}'
2026-07-11T19:49:58.4708350Z '1.48'
2026-07-11T19:49:58.4718280Z Docker daemon API version: '1.48'
2026-07-11T19:49:58.4719048Z ##[command]/usr/bin/docker version --format '{{.Client.APIVersion}}'
2026-07-11T19:49:58.4881612Z '1.48'
2026-07-11T19:49:58.4896476Z Docker client API version: '1.48'
2026-07-11T19:49:58.4902640Z ##[endgroup]
2026-07-11T19:49:58.4906101Z ##[group]Clean up resources from previous jobs
2026-07-11T19:49:58.4912174Z ##[command]/usr/bin/docker ps --all --quiet --no-trunc --filter "label=a0712e"
2026-07-11T19:49:58.5064001Z ##[command]/usr/bin/docker network prune --force --filter "label=a0712e"
2026-07-11T19:49:58.5204600Z ##[endgroup]
2026-07-11T19:49:58.5205140Z ##[group]Create local container network
2026-07-11T19:49:58.5215416Z ##[command]/usr/bin/docker network create --label a0712e github_network_48079045eec94823bfd27d4dad02e27d
2026-07-11T19:49:58.5727925Z 93a896671aa3822f43dbeaa411557204a39f7037978e0cdd8c0b1192357eceb5
2026-07-11T19:49:58.5747471Z ##[endgroup]
2026-07-11T19:49:58.5772390Z ##[group]Starting postgres service container
2026-07-11T19:49:58.5793882Z ##[command]/usr/bin/docker pull pgvector/pgvector:pg16
2026-07-11T19:49:58.7888898Z pg16: Pulling from pgvector/pgvector
2026-07-11T19:49:58.8790458Z 68629629b516: Pulling fs layer
2026-07-11T19:49:58.8791640Z 870f22c135c1: Pulling fs layer
2026-07-11T19:49:58.8792493Z 41297627cf85: Pulling fs layer
2026-07-11T19:49:58.8793336Z 65a3bbd5eb66: Pulling fs layer
2026-07-11T19:49:58.8794184Z 7b66c0a82cb1: Pulling fs layer
2026-07-11T19:49:58.8794831Z cc9adae34346: Pulling fs layer
2026-07-11T19:49:58.8795396Z cc6107e54361: Pulling fs layer
2026-07-11T19:49:58.8795943Z 612502b9ebdb: Pulling fs layer
2026-07-11T19:49:58.8796494Z ff38c5d8ae68: Pulling fs layer
2026-07-11T19:49:58.8797047Z f1c1c19fbf7f: Pulling fs layer
2026-07-11T19:49:58.8797631Z 11bb405b3d26: Pulling fs layer
2026-07-11T19:49:58.8798162Z c08a8fef47b5: Pulling fs layer
2026-07-11T19:49:58.8798708Z c13bbcdab63c: Pulling fs layer
2026-07-11T19:49:58.8799581Z 2b067480292d: Pulling fs layer
2026-07-11T19:49:58.8800638Z a27863b3f8d2: Pulling fs layer
2026-07-11T19:49:58.8801614Z 917c1c628740: Pulling fs layer
2026-07-11T19:49:58.8802466Z cc9adae34346: Waiting
2026-07-11T19:49:58.8803251Z c08a8fef47b5: Waiting
2026-07-11T19:49:58.8804022Z c13bbcdab63c: Waiting
2026-07-11T19:49:58.8804809Z 2b067480292d: Waiting
2026-07-11T19:49:58.8805586Z cc6107e54361: Waiting
2026-07-11T19:49:58.8806132Z a27863b3f8d2: Waiting
2026-07-11T19:49:58.8806584Z 612502b9ebdb: Waiting
2026-07-11T19:49:58.8807207Z 917c1c628740: Waiting
2026-07-11T19:49:58.8807701Z ff38c5d8ae68: Waiting
2026-07-11T19:49:58.8808624Z 11bb405b3d26: Waiting
2026-07-11T19:49:58.8809398Z f1c1c19fbf7f: Waiting
2026-07-11T19:49:58.8810402Z 65a3bbd5eb66: Waiting
2026-07-11T19:49:58.8811180Z 7b66c0a82cb1: Waiting
2026-07-11T19:49:58.9084039Z 870f22c135c1: Download complete
2026-07-11T19:49:58.9340476Z 41297627cf85: Verifying Checksum
2026-07-11T19:49:58.9344646Z 41297627cf85: Download complete
2026-07-11T19:49:58.9478235Z 65a3bbd5eb66: Verifying Checksum
2026-07-11T19:49:58.9479285Z 65a3bbd5eb66: Download complete
2026-07-11T19:49:58.9944216Z cc9adae34346: Verifying Checksum
2026-07-11T19:49:58.9945686Z cc9adae34346: Download complete
2026-07-11T19:49:59.0033049Z 7b66c0a82cb1: Verifying Checksum
2026-07-11T19:49:59.0034478Z 7b66c0a82cb1: Download complete
2026-07-11T19:49:59.0103537Z 68629629b516: Verifying Checksum
2026-07-11T19:49:59.0105404Z 68629629b516: Download complete
2026-07-11T19:49:59.0283107Z cc6107e54361: Verifying Checksum
2026-07-11T19:49:59.0285450Z cc6107e54361: Download complete
2026-07-11T19:49:59.0310669Z 612502b9ebdb: Download complete
2026-07-11T19:49:59.0599261Z 11bb405b3d26: Verifying Checksum
2026-07-11T19:49:59.0601176Z 11bb405b3d26: Download complete
2026-07-11T19:49:59.0613611Z f1c1c19fbf7f: Verifying Checksum
2026-07-11T19:49:59.0615177Z f1c1c19fbf7f: Download complete
2026-07-11T19:49:59.0902033Z c13bbcdab63c: Verifying Checksum
2026-07-11T19:49:59.0903654Z c13bbcdab63c: Download complete
2026-07-11T19:49:59.0923982Z c08a8fef47b5: Verifying Checksum
2026-07-11T19:49:59.0925345Z c08a8fef47b5: Download complete
2026-07-11T19:49:59.1214016Z 2b067480292d: Verifying Checksum
2026-07-11T19:49:59.1222970Z 2b067480292d: Download complete
2026-07-11T19:49:59.1282037Z a27863b3f8d2: Verifying Checksum
2026-07-11T19:49:59.1283423Z a27863b3f8d2: Download complete
2026-07-11T19:49:59.1692197Z 917c1c628740: Verifying Checksum
2026-07-11T19:49:59.1693199Z 917c1c628740: Download complete
2026-07-11T19:49:59.5869170Z ff38c5d8ae68: Verifying Checksum
2026-07-11T19:49:59.5882083Z ff38c5d8ae68: Download complete
2026-07-11T19:50:00.3289396Z 68629629b516: Pull complete
2026-07-11T19:50:01.5581261Z 870f22c135c1: Pull complete
2026-07-11T19:50:01.7144827Z 41297627cf85: Pull complete
2026-07-11T19:50:01.7623644Z 65a3bbd5eb66: Pull complete
2026-07-11T19:50:02.0928854Z 7b66c0a82cb1: Pull complete
2026-07-11T19:50:02.1970505Z cc9adae34346: Pull complete
2026-07-11T19:50:02.2080233Z cc6107e54361: Pull complete
2026-07-11T19:50:02.2198006Z 612502b9ebdb: Pull complete
2026-07-11T19:50:05.1769561Z ff38c5d8ae68: Pull complete
2026-07-11T19:50:05.1955424Z f1c1c19fbf7f: Pull complete
2026-07-11T19:50:05.2106066Z 11bb405b3d26: Pull complete
2026-07-11T19:50:05.2221005Z c08a8fef47b5: Pull complete
2026-07-11T19:50:05.2329736Z c13bbcdab63c: Pull complete
2026-07-11T19:50:05.2432534Z 2b067480292d: Pull complete
2026-07-11T19:50:05.2973930Z a27863b3f8d2: Pull complete
2026-07-11T19:50:05.3745322Z 917c1c628740: Pull complete
2026-07-11T19:50:05.3786034Z Digest: sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb
2026-07-11T19:50:05.3799379Z Status: Downloaded newer image for pgvector/pgvector:pg16
2026-07-11T19:50:05.3808454Z docker.io/pgvector/pgvector:pg16
2026-07-11T19:50:05.3871745Z ##[command]/usr/bin/docker create --name 04d11f3417ce45de9b5e1794ab2c5948_pgvectorpgvectorpg16_89083a --label a0712e --network github_network_48079045eec94823bfd27d4dad02e27d --network-alias postgres -p 5432:5432 --health-cmd "pg_isready -U postgres -d career_coach_test" --health-interval 5s --health-timeout 5s --health-retries 10 -e "POSTGRES_USER=postgres" -e "POSTGRES_PASSWORD=postgres" -e "POSTGRES_DB=career_coach_test" -e GITHUB_ACTIONS=true -e CI=true pgvector/pgvector:pg16
2026-07-11T19:50:05.4136622Z e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:05.4159914Z ##[command]/usr/bin/docker start e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:05.6231391Z e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:05.6257636Z ##[command]/usr/bin/docker ps --all --filter id=e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633 --filter status=running --no-trunc --format "{{.ID}} {{.Status}}"
2026-07-11T19:50:05.6394305Z e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633 Up Less than a second (health: starting)
2026-07-11T19:50:05.6421817Z ##[command]/usr/bin/docker port e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:05.6583850Z 5432/tcp -> 0.0.0.0:5432
2026-07-11T19:50:05.6585802Z 5432/tcp -> [::]:5432
2026-07-11T19:50:05.6633550Z ##[endgroup]
2026-07-11T19:50:05.6642447Z ##[group]Waiting for all services to be ready
2026-07-11T19:50:05.6655796Z ##[command]/usr/bin/docker inspect --format="{{if .Config.Healthcheck}}{{print .State.Health.Status}}{{end}}" e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:05.6815620Z starting
2026-07-11T19:50:05.6854595Z postgres service is starting, waiting 2 seconds before checking again.
2026-07-11T19:50:07.6859051Z ##[command]/usr/bin/docker inspect --format="{{if .Config.Healthcheck}}{{print .State.Health.Status}}{{end}}" e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:07.6985738Z starting
2026-07-11T19:50:07.6999649Z postgres service is starting, waiting 4 seconds before checking again.
2026-07-11T19:50:11.9631354Z ##[command]/usr/bin/docker inspect --format="{{if .Config.Healthcheck}}{{print .State.Health.Status}}{{end}}" e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:11.9762300Z healthy
2026-07-11T19:50:11.9777810Z postgres service is healthy.
2026-07-11T19:50:11.9778549Z ##[endgroup]
2026-07-11T19:50:12.0050492Z Node 20 is being deprecated. This workflow is running with Node 24 by default. If you need to temporarily use Node 20, you can set the ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION=true environment variable. For more information see: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/
2026-07-11T19:50:12.0124761Z ##[group]Run actions/checkout@v4
2026-07-11T19:50:12.0125907Z with:
2026-07-11T19:50:12.0126161Z   repository: nangelov/career-coach-agent
2026-07-11T19:50:12.0129069Z   token: ***
2026-07-11T19:50:12.0129283Z   ssh-strict: true
2026-07-11T19:50:12.0129491Z   ssh-user: git
2026-07-11T19:50:12.0129706Z   persist-credentials: true
2026-07-11T19:50:12.0129938Z   clean: true
2026-07-11T19:50:12.0130375Z   sparse-checkout-cone-mode: true
2026-07-11T19:50:12.0130649Z   fetch-depth: 1
2026-07-11T19:50:12.0130864Z   fetch-tags: false
2026-07-11T19:50:12.0131092Z   show-progress: true
2026-07-11T19:50:12.0131294Z   lfs: false
2026-07-11T19:50:12.0131520Z   submodules: false
2026-07-11T19:50:12.0131722Z   set-safe-directory: true
2026-07-11T19:50:12.0132258Z env:
2026-07-11T19:50:12.0132469Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:12.0132756Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:12.0133363Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:12.0133658Z ##[endgroup]
2026-07-11T19:50:12.1125800Z Syncing repository: nangelov/career-coach-agent
2026-07-11T19:50:12.1127674Z ##[group]Getting Git version info
2026-07-11T19:50:12.1128396Z Working directory is '/home/runner/work/career-coach-agent/career-coach-agent'
2026-07-11T19:50:12.1129411Z [command]/usr/bin/git version
2026-07-11T19:50:12.1183429Z git version 2.54.0
2026-07-11T19:50:12.1204960Z ##[endgroup]
2026-07-11T19:50:12.1219860Z Temporarily overriding HOME='/home/runner/work/_temp/e9947732-5b0c-41ef-9c4d-8c8a88ad70ec' before making global git config changes
2026-07-11T19:50:12.1221574Z Adding repository directory to the temporary git global config as a safe directory
2026-07-11T19:50:12.1225750Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/career-coach-agent/career-coach-agent
2026-07-11T19:50:12.1280648Z Deleting the contents of '/home/runner/work/career-coach-agent/career-coach-agent'
2026-07-11T19:50:12.1285922Z ##[group]Initializing the repository
2026-07-11T19:50:12.1293231Z [command]/usr/bin/git init /home/runner/work/career-coach-agent/career-coach-agent
2026-07-11T19:50:12.1404231Z hint: Using 'master' as the name for the initial branch. This default branch name
2026-07-11T19:50:12.1409468Z hint: will change to "main" in Git 3.0. To configure the initial branch name
2026-07-11T19:50:12.1410753Z hint: to use in all of your new repositories, which will suppress this warning,
2026-07-11T19:50:12.1411541Z hint: call:
2026-07-11T19:50:12.1411889Z hint:
2026-07-11T19:50:12.1412438Z hint: 	git config --global init.defaultBranch <name>
2026-07-11T19:50:12.1413079Z hint:
2026-07-11T19:50:12.1413625Z hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and
2026-07-11T19:50:12.1414529Z hint: 'development'. The just-created branch can be renamed via this command:
2026-07-11T19:50:12.1415254Z hint:
2026-07-11T19:50:12.1415627Z hint: 	git branch -m <name>
2026-07-11T19:50:12.1416045Z hint:
2026-07-11T19:50:12.1416597Z hint: Disable this message with "git config set advice.defaultBranchName false"
2026-07-11T19:50:12.1417663Z Initialized empty Git repository in /home/runner/work/career-coach-agent/career-coach-agent/.git/
2026-07-11T19:50:12.1423352Z [command]/usr/bin/git remote add origin https://github.com/nangelov/career-coach-agent
2026-07-11T19:50:12.1503267Z ##[endgroup]
2026-07-11T19:50:12.1503976Z ##[group]Disabling automatic garbage collection
2026-07-11T19:50:12.1508520Z [command]/usr/bin/git config --local gc.auto 0
2026-07-11T19:50:12.1548090Z ##[endgroup]
2026-07-11T19:50:12.1550426Z ##[group]Setting up auth
2026-07-11T19:50:12.1560436Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-07-11T19:50:12.1597330Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-07-11T19:50:12.1978026Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-07-11T19:50:12.2032983Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-07-11T19:50:12.2278758Z [command]/usr/bin/git config --local --name-only --get-regexp ^includeIf\.gitdir:
2026-07-11T19:50:12.2318076Z [command]/usr/bin/git submodule foreach --recursive git config --local --show-origin --name-only --get-regexp remote.origin.url
2026-07-11T19:50:12.2554438Z [command]/usr/bin/git config --local http.https://github.com/.extraheader AUTHORIZATION: basic ***
2026-07-11T19:50:12.2595186Z ##[endgroup]
2026-07-11T19:50:12.2595645Z ##[group]Fetching the repository
2026-07-11T19:50:12.2605203Z [command]/usr/bin/git -c protocol.version=2 fetch --no-tags --prune --no-recurse-submodules --depth=1 origin +5b83e49d5a9c0535d1db17315e3907212862aece:refs/remotes/origin/version-2
2026-07-11T19:50:12.6149351Z From https://github.com/nangelov/career-coach-agent
2026-07-11T19:50:12.6150559Z  * [new ref]         5b83e49d5a9c0535d1db17315e3907212862aece -> origin/version-2
2026-07-11T19:50:12.6184149Z ##[endgroup]
2026-07-11T19:50:12.6184821Z ##[group]Determining the checkout info
2026-07-11T19:50:12.6187201Z ##[endgroup]
2026-07-11T19:50:12.6195380Z [command]/usr/bin/git sparse-checkout disable
2026-07-11T19:50:12.6248046Z [command]/usr/bin/git config --local --unset-all extensions.worktreeConfig
2026-07-11T19:50:12.6280454Z ##[group]Checking out the ref
2026-07-11T19:50:12.6286862Z [command]/usr/bin/git checkout --progress --force -B version-2 refs/remotes/origin/version-2
2026-07-11T19:50:12.6708061Z Switched to a new branch 'version-2'
2026-07-11T19:50:12.6711438Z branch 'version-2' set up to track 'origin/version-2'.
2026-07-11T19:50:12.6718855Z ##[endgroup]
2026-07-11T19:50:12.6771646Z [command]/usr/bin/git log -1 --format=%H
2026-07-11T19:50:12.6798267Z 5b83e49d5a9c0535d1db17315e3907212862aece
2026-07-11T19:50:12.7030938Z Node 20 is being deprecated. This workflow is running with Node 24 by default. If you need to temporarily use Node 20, you can set the ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION=true environment variable. For more information see: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/
2026-07-11T19:50:12.7032606Z ##[group]Run astral-sh/setup-uv@v5
2026-07-11T19:50:12.7032868Z with:
2026-07-11T19:50:12.7033058Z   enable-cache: true
2026-07-11T19:50:12.7035537Z   github-token: ***
2026-07-11T19:50:12.7035835Z   cache-dependency-glob: **/uv.lock
**/requirements*.txt

2026-07-11T19:50:12.7036178Z   prune-cache: true
2026-07-11T19:50:12.7036409Z   ignore-nothing-to-cache: false
2026-07-11T19:50:12.7036668Z   ignore-empty-workdir: false
2026-07-11T19:50:12.7036901Z env:
2026-07-11T19:50:12.7037095Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:12.7037363Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:12.7037948Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:12.7038242Z ##[endgroup]
2026-07-11T19:50:12.8698812Z (node:2712) [DEP0040] DeprecationWarning: The `punycode` module is deprecated. Please use a userland alternative instead.
2026-07-11T19:50:12.8699598Z (Use `node --trace-deprecation ...` to show where the warning was created)
2026-07-11T19:50:13.1123820Z Downloading uv from "https://github.com/astral-sh/uv/releases/download/0.11.28/uv-x86_64-unknown-linux-gnu.tar.gz" ...
2026-07-11T19:50:13.3516365Z [command]/usr/bin/tar xz --warning=no-unknown-keyword --overwrite -C /home/runner/work/_temp/726a6777-4a69-42bb-9407-3d63736671e8 -f /home/runner/work/_temp/9ca0f0fe-7cf7-44ce-9ddc-f90012ce15dc
2026-07-11T19:50:13.8699487Z Added /home/runner/.local/bin to the path
2026-07-11T19:50:13.8703016Z Added /opt/hostedtoolcache/uv/0.11.28/x86_64 to the path
2026-07-11T19:50:13.8731326Z Set UV_CACHE_DIR to /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:13.8731992Z Successfully installed uv version 0.11.28
2026-07-11T19:50:13.8732771Z Searching files using cache dependency glob: **/uv.lock,**/requirements*.txt
2026-07-11T19:50:13.9138021Z /home/runner/work/career-coach-agent/career-coach-agent/backend/uv.lock
2026-07-11T19:50:13.9537703Z /home/runner/work/career-coach-agent/career-coach-agent/legacy-code/requirements.txt
2026-07-11T19:50:13.9550771Z Found 2 files to hash.
2026-07-11T19:50:14.0341461Z Trying to restore uv cache from GitHub Actions cache with key: setup-uv-1-x86_64-unknown-linux-gnu-3.12.3-4662f609658c17a5eb507d4abeed05a94057d58e5006879e7fd0b7323605f258
2026-07-11T19:50:14.0791661Z Cache hit for: setup-uv-1-x86_64-unknown-linux-gnu-3.12.3-4662f609658c17a5eb507d4abeed05a94057d58e5006879e7fd0b7323605f258
2026-07-11T19:50:14.0908463Z (node:2712) [DEP0169] DeprecationWarning: `url.parse()` behavior is not standardized and prone to errors that have security implications. Use the WHATWG URL API instead. CVEs are not issued for `url.parse()` vulnerabilities.
2026-07-11T19:50:14.2637654Z Received 4323155 of 4323155 (100.0%), 31.0 MBs/sec
2026-07-11T19:50:14.2638422Z Cache Size: ~4 MB (4323155 B)
2026-07-11T19:50:14.2675106Z [command]/usr/bin/tar -xf /home/runner/work/_temp/52abeaca-e8ac-4d3c-89d2-a7d48245bc6f/cache.tzst -P -C /home/runner/work/career-coach-agent/career-coach-agent --use-compress-program unzstd
2026-07-11T19:50:14.3064702Z Cache restored successfully
2026-07-11T19:50:14.3073664Z uv cache restored from GitHub Actions cache with key: setup-uv-1-x86_64-unknown-linux-gnu-3.12.3-4662f609658c17a5eb507d4abeed05a94057d58e5006879e7fd0b7323605f258
2026-07-11T19:50:14.3235386Z ##[group]Run uv python install 3.11
2026-07-11T19:50:14.3235748Z [36;1muv python install 3.11[0m
2026-07-11T19:50:14.3274071Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:14.3274343Z env:
2026-07-11T19:50:14.3274560Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:14.3274862Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:14.3275479Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:14.3275852Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:14.3276155Z ##[endgroup]
2026-07-11T19:50:14.4535924Z Downloading cpython-3.11.15-linux-x86_64-gnu (download) (29.5MiB)
2026-07-11T19:50:15.3690909Z  Downloaded cpython-3.11.15-linux-x86_64-gnu (download)
2026-07-11T19:50:15.3736107Z Installed Python 3.11.15 in 1.02s
2026-07-11T19:50:15.3736911Z  + cpython-3.11.15-linux-x86_64-gnu (python3.11)
2026-07-11T19:50:15.3789682Z ##[group]Run uv sync --only-group dev
2026-07-11T19:50:15.3790374Z [36;1muv sync --only-group dev[0m
2026-07-11T19:50:15.3790833Z [36;1muv pip install fastapi pydantic pydantic-settings "celery[redis]" openai \[0m
2026-07-11T19:50:15.3791361Z [36;1m  sqlalchemy asyncpg aiosqlite pgvector alembic joserfc[0m
2026-07-11T19:50:15.3824992Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:15.3825250Z env:
2026-07-11T19:50:15.3825456Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:15.3825749Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:15.3826382Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:15.3826754Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:15.3827064Z ##[endgroup]
2026-07-11T19:50:15.5221725Z Using CPython 3.11.15
2026-07-11T19:50:15.5222235Z Creating virtual environment at: .venv
2026-07-11T19:50:15.5372184Z Resolved 206 packages in 0.76ms
2026-07-11T19:50:15.6138494Z Downloading ruff (11.0MiB)
2026-07-11T19:50:15.6139463Z Downloading ast-serialize (1.2MiB)
2026-07-11T19:50:15.6143060Z Downloading pygments (1.2MiB)
2026-07-11T19:50:15.6148452Z Downloading mypy (14.2MiB)
2026-07-11T19:50:15.7421780Z  Downloaded ast-serialize
2026-07-11T19:50:15.8965460Z  Downloaded ruff
2026-07-11T19:50:15.9639597Z  Downloaded pygments
2026-07-11T19:50:16.1477689Z  Downloaded mypy
2026-07-11T19:50:16.1480780Z Prepared 25 packages in 610ms
2026-07-11T19:50:16.1842348Z Installed 25 packages in 36ms
2026-07-11T19:50:16.1842880Z  + anyio==4.14.1
2026-07-11T19:50:16.1843286Z  + ast-serialize==0.5.0
2026-07-11T19:50:16.1843682Z  + attrs==26.1.0
2026-07-11T19:50:16.1844044Z  + celery-types==0.26.0
2026-07-11T19:50:16.1844446Z  + certifi==2026.6.17
2026-07-11T19:50:16.1844798Z  + h11==0.16.0
2026-07-11T19:50:16.1845147Z  + httpcore==1.0.9
2026-07-11T19:50:16.1845511Z  + httpx==0.28.1
2026-07-11T19:50:16.1845854Z  + idna==3.18
2026-07-11T19:50:16.1846197Z  + iniconfig==2.3.0
2026-07-11T19:50:16.1846553Z  + librt==0.11.0
2026-07-11T19:50:16.1846942Z  + mypy==2.1.0
2026-07-11T19:50:16.1847294Z  + mypy-extensions==1.1.0
2026-07-11T19:50:16.1847661Z  + outcome==1.3.0.post0
2026-07-11T19:50:16.1848014Z  + packaging==26.2
2026-07-11T19:50:16.1857390Z  + pathspec==1.1.1
2026-07-11T19:50:16.1859353Z  + pluggy==1.6.0
2026-07-11T19:50:16.1859955Z  + pygments==2.20.0
2026-07-11T19:50:16.1860577Z  + pytest==9.1.1
2026-07-11T19:50:16.1860947Z  + pytest-asyncio==1.4.0
2026-07-11T19:50:16.1861332Z  + ruff==0.15.20
2026-07-11T19:50:16.1861658Z  + sniffio==1.3.1
2026-07-11T19:50:16.1862011Z  + sortedcontainers==2.4.0
2026-07-11T19:50:16.1862369Z  + trio==0.33.0
2026-07-11T19:50:16.1862599Z  + typing-extensions==4.15.0
2026-07-11T19:50:16.5757965Z Resolved 50 packages in 256ms
2026-07-11T19:50:16.5915616Z Downloading openai (1.6MiB)
2026-07-11T19:50:16.5947841Z Downloading asyncpg (2.8MiB)
2026-07-11T19:50:16.5990266Z Downloading cryptography (4.5MiB)
2026-07-11T19:50:16.5995134Z Downloading pydantic-core (2.0MiB)
2026-07-11T19:50:16.6098437Z Downloading sqlalchemy (3.2MiB)
2026-07-11T19:50:16.7736954Z  Downloaded pydantic-core
2026-07-11T19:50:16.8409235Z  Downloaded asyncpg
2026-07-11T19:50:16.8677272Z  Downloaded cryptography
2026-07-11T19:50:16.8952309Z  Downloaded sqlalchemy
2026-07-11T19:50:17.0501254Z  Downloaded openai
2026-07-11T19:50:17.0504027Z Prepared 41 packages in 473ms
2026-07-11T19:50:17.1033499Z Installed 41 packages in 52ms
2026-07-11T19:50:17.1033995Z  + aiosqlite==0.22.1
2026-07-11T19:50:17.1034375Z  + alembic==1.18.5
2026-07-11T19:50:17.1034720Z  + amqp==5.3.1
2026-07-11T19:50:17.1035077Z  + annotated-doc==0.0.4
2026-07-11T19:50:17.1035480Z  + annotated-types==0.7.0
2026-07-11T19:50:17.1035936Z  + asyncpg==0.31.0
2026-07-11T19:50:17.1036577Z  + billiard==4.2.4
2026-07-11T19:50:17.1036991Z  + celery==5.6.3
2026-07-11T19:50:17.1037458Z  + cffi==2.1.0
2026-07-11T19:50:17.1037959Z  + click==8.4.2
2026-07-11T19:50:17.1038497Z  + click-didyoumean==0.3.1
2026-07-11T19:50:17.1039103Z  + click-plugins==1.1.1.2
2026-07-11T19:50:17.1039915Z  + click-repl==0.3.0
2026-07-11T19:50:17.1040599Z  + cryptography==49.0.0
2026-07-11T19:50:17.1041003Z  + distro==1.9.0
2026-07-11T19:50:17.1041356Z  + fastapi==0.139.0
2026-07-11T19:50:17.1041864Z  + greenlet==3.5.3
2026-07-11T19:50:17.1042342Z  + jiter==0.16.0
2026-07-11T19:50:17.1042864Z  + joserfc==1.7.3
2026-07-11T19:50:17.1043235Z  + kombu==5.6.2
2026-07-11T19:50:17.1043602Z  + mako==1.3.12
2026-07-11T19:50:17.1044012Z  + markupsafe==3.0.3
2026-07-11T19:50:17.1044420Z  + openai==2.45.0
2026-07-11T19:50:17.1051144Z  + pgvector==0.5.0
2026-07-11T19:50:17.1051577Z  + prompt-toolkit==3.0.52
2026-07-11T19:50:17.1051969Z  + pycparser==3.0
2026-07-11T19:50:17.1052279Z  + pydantic==2.13.4
2026-07-11T19:50:17.1052537Z  + pydantic-core==2.46.4
2026-07-11T19:50:17.1052784Z  + pydantic-settings==2.14.2
2026-07-11T19:50:17.1053031Z  + python-dateutil==2.9.0.post0
2026-07-11T19:50:17.1053295Z  + python-dotenv==1.2.2
2026-07-11T19:50:17.1053511Z  + redis==6.4.0
2026-07-11T19:50:17.1053699Z  + six==1.17.0
2026-07-11T19:50:17.1053905Z  + sqlalchemy==2.0.51
2026-07-11T19:50:17.1054112Z  + starlette==1.3.1
2026-07-11T19:50:17.1054318Z  + tqdm==4.68.4
2026-07-11T19:50:17.1054518Z  + typing-inspection==0.4.2
2026-07-11T19:50:17.1054744Z  + tzdata==2026.3
2026-07-11T19:50:17.1054933Z  + tzlocal==5.4.4
2026-07-11T19:50:17.1055286Z  + vine==5.1.0
2026-07-11T19:50:17.1055600Z  + wcwidth==0.8.2
2026-07-11T19:50:17.1136133Z ##[group]Run uv run --no-sync ruff check .
2026-07-11T19:50:17.1136507Z [36;1muv run --no-sync ruff check .[0m
2026-07-11T19:50:17.1169116Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:17.1169371Z env:
2026-07-11T19:50:17.1169582Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:17.1169875Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:17.1170764Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:17.1171140Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:17.1171449Z ##[endgroup]
2026-07-11T19:50:17.1605189Z All checks passed!
2026-07-11T19:50:17.1649486Z ##[group]Run uv run --no-sync ruff format --check .
2026-07-11T19:50:17.1649896Z [36;1muv run --no-sync ruff format --check .[0m
2026-07-11T19:50:17.1683217Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:17.1683472Z env:
2026-07-11T19:50:17.1683685Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:17.1683970Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:17.1684571Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:17.1684939Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:17.1685238Z ##[endgroup]
2026-07-11T19:50:17.2126190Z 126 files already formatted
2026-07-11T19:50:17.2169480Z ##[group]Run uv run --no-sync mypy app/ migrations/
2026-07-11T19:50:17.2169920Z [36;1muv run --no-sync mypy app/ migrations/[0m
2026-07-11T19:50:17.2203629Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:17.2203891Z env:
2026-07-11T19:50:17.2204099Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:17.2204400Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:17.2205012Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:17.2205380Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:17.2205872Z ##[endgroup]
2026-07-11T19:50:32.2031629Z Success: no issues found in 75 source files
2026-07-11T19:50:32.2501494Z ##[group]Run docker exec -i "e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633" \
2026-07-11T19:50:32.2502241Z [36;1mdocker exec -i "e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633" \[0m
2026-07-11T19:50:32.2502754Z [36;1m  psql -U postgres -d career_coach_test \[0m
2026-07-11T19:50:32.2503103Z [36;1m  < migrations/init/01_enable_pgvector.sql[0m
2026-07-11T19:50:32.2535110Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:32.2535360Z env:
2026-07-11T19:50:32.2535570Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:32.2535851Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:32.2536572Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:32.2536937Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:32.2537232Z ##[endgroup]
2026-07-11T19:50:32.3507449Z CREATE EXTENSION
2026-07-11T19:50:32.3569121Z ##[group]Run uv run --no-sync alembic upgrade head
2026-07-11T19:50:32.3569529Z [36;1muv run --no-sync alembic upgrade head[0m
2026-07-11T19:50:32.3601883Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:32.3602135Z env:
2026-07-11T19:50:32.3602346Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:32.3602633Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:32.3603253Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:32.3603614Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:32.3603915Z ##[endgroup]
2026-07-11T19:50:35.1359921Z INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
2026-07-11T19:50:35.1360724Z INFO  [alembic.runtime.migration] Will assume transactional DDL.
2026-07-11T19:50:35.1565489Z INFO  [alembic.runtime.migration] Running upgrade  -> 0001, baseline — empty starting point for the v2 schema.
2026-07-11T19:50:35.1580718Z INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, identity and docs tables — first real v2 schema (P2-03).
2026-07-11T19:50:35.2040768Z INFO  [alembic.runtime.migration] Running upgrade 0002 -> 0003, knowledge and vector tables — pgvector table group (P2-04).
2026-07-11T19:50:35.2257453Z INFO  [alembic.runtime.migration] Running upgrade 0003 -> 0004, structured records — jobs, PDPs & dashboard table group (P2-05).
2026-07-11T19:50:35.2630354Z INFO  [alembic.runtime.migration] Running upgrade 0004 -> 0005, admin flag on users — real admin auth (P3-05).
2026-07-11T19:50:35.4697316Z ##[group]Run uv run --no-sync pytest
2026-07-11T19:50:35.4697718Z [36;1muv run --no-sync pytest[0m
2026-07-11T19:50:35.4731170Z shell: /usr/bin/bash -e {0}
2026-07-11T19:50:35.4731426Z env:
2026-07-11T19:50:35.4731634Z   HF_API_TOKEN: ci-not-a-real-token
2026-07-11T19:50:35.4731918Z   JWT_SECRET_KEY: ci-not-a-real-secret
2026-07-11T19:50:35.4732527Z   DATABASE_URL: ***localhost:5432/career_coach_test
2026-07-11T19:50:35.4732909Z   UV_CACHE_DIR: /home/runner/work/_temp/setup-uv-cache
2026-07-11T19:50:35.4733238Z ##[endgroup]
2026-07-11T19:50:38.7089466Z ============================= test session starts ==============================
2026-07-11T19:50:38.7090579Z platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0
2026-07-11T19:50:38.7091387Z rootdir: /home/runner/work/career-coach-agent/career-coach-agent/backend
2026-07-11T19:50:38.7092100Z configfile: pyproject.toml
2026-07-11T19:50:38.7092525Z testpaths: tests
2026-07-11T19:50:38.7093005Z plugins: asyncio-1.4.0, anyio-4.14.1
2026-07-11T19:50:38.7093937Z asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
2026-07-11T19:50:38.7094866Z collected 131 items / 27 errors
2026-07-11T19:50:38.7095145Z 
2026-07-11T19:50:38.7095369Z ==================================== ERRORS ====================================
2026-07-11T19:50:38.7096115Z ______________ ERROR collecting tests/test_admin_feedback_api.py _______________
2026-07-11T19:50:38.7097732Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_admin_feedback_api.py'.
2026-07-11T19:50:38.7098462Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7098824Z Traceback:
2026-07-11T19:50:38.7099306Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7099924Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7100713Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7101040Z tests/test_admin_feedback_api.py:23: in <module>
2026-07-11T19:50:38.7101376Z     from app.api.feedback import get_feedback_reader
2026-07-11T19:50:38.7101690Z app/api/feedback.py:21: in <module>
2026-07-11T19:50:38.7101981Z     from app.bootstrap import build_feedback_reader
2026-07-11T19:50:38.7102288Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7102582Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7102903Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7103214Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7103563Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7103966Z __________________ ERROR collecting tests/test_agent_graph.py __________________
2026-07-11T19:50:38.7104680Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_agent_graph.py'.
2026-07-11T19:50:38.7105370Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7105716Z Traceback:
2026-07-11T19:50:38.7106189Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7106795Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7107154Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7107456Z tests/test_agent_graph.py:27: in <module>
2026-07-11T19:50:38.7107804Z     from langgraph.graph.state import CompiledStateGraph
2026-07-11T19:50:38.7108171Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7108584Z _________________ ERROR collecting tests/test_agent_planner.py _________________
2026-07-11T19:50:38.7109299Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_agent_planner.py'.
2026-07-11T19:50:38.7110435Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7110821Z Traceback:
2026-07-11T19:50:38.7111300Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7111902Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7112254Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7112554Z tests/test_agent_planner.py:25: in <module>
2026-07-11T19:50:38.7112863Z     from app.agents.graph import (
2026-07-11T19:50:38.7113138Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7113419Z     from app.agents.graph import (
2026-07-11T19:50:38.7113684Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7113987Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7114345Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7114765Z ________________ ERROR collecting tests/test_agent_responder.py ________________
2026-07-11T19:50:38.7115491Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_agent_responder.py'.
2026-07-11T19:50:38.7116190Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7116544Z Traceback:
2026-07-11T19:50:38.7117004Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7117751Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7118102Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7118410Z tests/test_agent_responder.py:24: in <module>
2026-07-11T19:50:38.7118764Z     from app.agents.graph import build_graph, stream_graph
2026-07-11T19:50:38.7119093Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7119362Z     from app.agents.graph import (
2026-07-11T19:50:38.7119628Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7119923Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7120527Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7120938Z __________________ ERROR collecting tests/test_agent_state.py __________________
2026-07-11T19:50:38.7121638Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_agent_state.py'.
2026-07-11T19:50:38.7122377Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7122718Z Traceback:
2026-07-11T19:50:38.7123178Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7123775Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7124124Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7124426Z tests/test_agent_state.py:21: in <module>
2026-07-11T19:50:38.7124750Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7125096Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7125502Z ___________________ ERROR collecting tests/test_auth_api.py ____________________
2026-07-11T19:50:38.7126181Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_auth_api.py'.
2026-07-11T19:50:38.7126838Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7127181Z Traceback:
2026-07-11T19:50:38.7127629Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7128221Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7128575Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7128866Z tests/test_auth_api.py:16: in <module>
2026-07-11T19:50:38.7129483Z     from app.api.auth import get_guest_auth_service
2026-07-11T19:50:38.7129798Z app/api/auth.py:25: in <module>
2026-07-11T19:50:38.7130414Z     from app.bootstrap import (
2026-07-11T19:50:38.7130856Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7131353Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7131907Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7132432Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7132891Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7133305Z _________________ ERROR collecting tests/test_auth_service.py __________________
2026-07-11T19:50:38.7134014Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_auth_service.py'.
2026-07-11T19:50:38.7134694Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7135041Z Traceback:
2026-07-11T19:50:38.7135502Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7136103Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7136456Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7136761Z tests/test_auth_service.py:13: in <module>
2026-07-11T19:50:38.7137072Z     from app.services.auth import GuestAuthService
2026-07-11T19:50:38.7137383Z app/services/auth.py:35: in <module>
2026-07-11T19:50:38.7137815Z     from app.security.oidc import OIDCClient
2026-07-11T19:50:38.7138101Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7138400Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7138744Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7139147Z ______________ ERROR collecting tests/test_authz_ratelimit_api.py ______________
2026-07-11T19:50:38.7139891Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_authz_ratelimit_api.py'.
2026-07-11T19:50:38.7142115Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7142473Z Traceback:
2026-07-11T19:50:38.7142947Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7143557Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7143917Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7144256Z tests/test_authz_ratelimit_api.py:21: in <module>
2026-07-11T19:50:38.7144581Z     from app.api.chat import get_chat_service
2026-07-11T19:50:38.7144871Z app/api/chat.py:34: in <module>
2026-07-11T19:50:38.7145143Z     from app.bootstrap import build_chat_service
2026-07-11T19:50:38.7145446Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7145734Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7146059Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7146375Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7146722Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7147123Z ___________________ ERROR collecting tests/test_chat_api.py ____________________
2026-07-11T19:50:38.7147817Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_chat_api.py'.
2026-07-11T19:50:38.7148489Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7148842Z Traceback:
2026-07-11T19:50:38.7149302Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7149906Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7150538Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7150844Z tests/test_chat_api.py:24: in <module>
2026-07-11T19:50:38.7151401Z     from app.agents.graph import GraphTurnStreamer
2026-07-11T19:50:38.7151752Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7152031Z     from app.agents.graph import (
2026-07-11T19:50:38.7152303Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7152611Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7152970Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7153383Z __________________ ERROR collecting tests/test_chat_cancel.py __________________
2026-07-11T19:50:38.7154092Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_chat_cancel.py'.
2026-07-11T19:50:38.7154773Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7155115Z Traceback:
2026-07-11T19:50:38.7155572Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7156170Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7156520Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7156823Z tests/test_chat_cancel.py:23: in <module>
2026-07-11T19:50:38.7157120Z     from app.api.chat import get_chat_service
2026-07-11T19:50:38.7157408Z app/api/chat.py:34: in <module>
2026-07-11T19:50:38.7157673Z     from app.bootstrap import build_chat_service
2026-07-11T19:50:38.7157970Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7158259Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7158765Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7159082Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7159428Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7159834Z _______________ ERROR collecting tests/test_chat_persistence.py ________________
2026-07-11T19:50:38.7160838Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_chat_persistence.py'.
2026-07-11T19:50:38.7161535Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7161873Z Traceback:
2026-07-11T19:50:38.7162333Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7162928Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7163276Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7163611Z tests/test_chat_persistence.py:29: in <module>
2026-07-11T19:50:38.7173523Z     from app.services.chat import ChatService, GraphTurnRunner
2026-07-11T19:50:38.7174077Z app/services/chat.py:42: in <module>
2026-07-11T19:50:38.7174632Z     from app.agents.state import AgentState, Citation
2026-07-11T19:50:38.7175203Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7175709Z     from app.agents.graph import (
2026-07-11T19:50:38.7176177Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7176740Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7177373Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7178139Z _________________ ERROR collecting tests/test_chat_service.py __________________
2026-07-11T19:50:38.7179432Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_chat_service.py'.
2026-07-11T19:50:38.7180984Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7181596Z Traceback:
2026-07-11T19:50:38.7182445Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7183557Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7184209Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7184755Z tests/test_chat_service.py:18: in <module>
2026-07-11T19:50:38.7185801Z     from app.agents.state import Citation, Intent, PlannerDecision, WorkerName
2026-07-11T19:50:38.7186554Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7187047Z     from app.agents.graph import (
2026-07-11T19:50:38.7187513Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7188048Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7188684Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7189550Z _______________ ERROR collecting tests/test_guest_upgrade_api.py _______________
2026-07-11T19:50:38.7191139Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_guest_upgrade_api.py'.
2026-07-11T19:50:38.7192431Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7193052Z Traceback:
2026-07-11T19:50:38.7193882Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7195028Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7195671Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7196235Z tests/test_guest_upgrade_api.py:20: in <module>
2026-07-11T19:50:38.7196783Z     from app.api.auth import (
2026-07-11T19:50:38.7197229Z app/api/auth.py:25: in <module>
2026-07-11T19:50:38.7197660Z     from app.bootstrap import (
2026-07-11T19:50:38.7198046Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7198560Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7198899Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7199238Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7199603Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7200273Z ____________________ ERROR collecting tests/test_health.py _____________________
2026-07-11T19:50:38.7201041Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_health.py'.
2026-07-11T19:50:38.7201915Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7202467Z Traceback:
2026-07-11T19:50:38.7203283Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7204251Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7204816Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7205366Z tests/test_health.py:14: in <module>
2026-07-11T19:50:38.7205861Z     from app.main import app
2026-07-11T19:50:38.7206307Z app/main.py:29: in <module>
2026-07-11T19:50:38.7206775Z     from .api.auth import router as auth_router
2026-07-11T19:50:38.7207285Z app/api/auth.py:25: in <module>
2026-07-11T19:50:38.7207745Z     from app.bootstrap import (
2026-07-11T19:50:38.7208220Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7208739Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7209288Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7209806Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7210474Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7210895Z _______________ ERROR collecting tests/test_input_guardrails.py ________________
2026-07-11T19:50:38.7211637Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_input_guardrails.py'.
2026-07-11T19:50:38.7212349Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7212695Z Traceback:
2026-07-11T19:50:38.7213163Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7213767Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7214124Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7214609Z tests/test_input_guardrails.py:25: in <module>
2026-07-11T19:50:38.7214975Z     from langgraph.graph.state import CompiledStateGraph
2026-07-11T19:50:38.7215349Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7215758Z __________________ ERROR collecting tests/test_message_id.py ___________________
2026-07-11T19:50:38.7216456Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_message_id.py'.
2026-07-11T19:50:38.7217136Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7217493Z Traceback:
2026-07-11T19:50:38.7217952Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7218551Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7218899Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7219201Z tests/test_message_id.py:34: in <module>
2026-07-11T19:50:38.7219505Z     from app.services.chat import ChatService
2026-07-11T19:50:38.7219812Z app/services/chat.py:42: in <module>
2026-07-11T19:50:38.7220414Z     from app.agents.state import AgentState, Citation
2026-07-11T19:50:38.7220737Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7221009Z     from app.agents.graph import (
2026-07-11T19:50:38.7221272Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7221571Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7222068Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7222485Z __________________ ERROR collecting tests/test_oidc_client.py __________________
2026-07-11T19:50:38.7223190Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_oidc_client.py'.
2026-07-11T19:50:38.7223863Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7224202Z Traceback:
2026-07-11T19:50:38.7224667Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7225272Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7225625Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7225924Z tests/test_oidc_client.py:14: in <module>
2026-07-11T19:50:38.7226328Z     from app.security.oidc import AuthlibOIDCClient, OIDCError, ProviderConfig
2026-07-11T19:50:38.7226744Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7227054Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7227405Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7227824Z _____________ ERROR collecting tests/test_p2_exit_verification.py ______________
2026-07-11T19:50:38.7228564Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_p2_exit_verification.py'.
2026-07-11T19:50:38.7229275Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7229611Z Traceback:
2026-07-11T19:50:38.7230256Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7230871Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7231219Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7231551Z tests/test_p2_exit_verification.py:53: in <module>
2026-07-11T19:50:38.7231877Z     from app.api.chat import get_chat_service
2026-07-11T19:50:38.7232167Z app/api/chat.py:34: in <module>
2026-07-11T19:50:38.7232438Z     from app.bootstrap import build_chat_service
2026-07-11T19:50:38.7232736Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7233030Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7233345Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7233784Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7234137Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7234541Z _____________ ERROR collecting tests/test_p3_exit_verification.py ______________
2026-07-11T19:50:38.7235281Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_p3_exit_verification.py'.
2026-07-11T19:50:38.7235993Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7236341Z Traceback:
2026-07-11T19:50:38.7236790Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7237383Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7237733Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7238058Z tests/test_p3_exit_verification.py:37: in <module>
2026-07-11T19:50:38.7238366Z     from app.api.auth import (
2026-07-11T19:50:38.7238618Z app/api/auth.py:25: in <module>
2026-07-11T19:50:38.7238865Z     from app.bootstrap import (
2026-07-11T19:50:38.7239118Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7239405Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7239718Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7240164Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7240510Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7241059Z _____________ ERROR collecting tests/test_p4_exit_verification.py ______________
2026-07-11T19:50:38.7241789Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_p4_exit_verification.py'.
2026-07-11T19:50:38.7242490Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7242829Z Traceback:
2026-07-11T19:50:38.7243289Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7243883Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7244231Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7244547Z tests/test_p4_exit_verification.py:52: in <module>
2026-07-11T19:50:38.7244880Z     from app.agents.graph import GraphTurnStreamer
2026-07-11T19:50:38.7245180Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7245454Z     from app.agents.graph import (
2026-07-11T19:50:38.7245731Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7246027Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7246381Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7246780Z ___________________ ERROR collecting tests/test_rag_agent.py ___________________
2026-07-11T19:50:38.7247462Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_rag_agent.py'.
2026-07-11T19:50:38.7248123Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7248458Z Traceback:
2026-07-11T19:50:38.7248903Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7249497Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7249841Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7250264Z tests/test_rag_agent.py:32: in <module>
2026-07-11T19:50:38.7250553Z     from app.agents.graph import build_graph
2026-07-11T19:50:38.7250844Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7251109Z     from app.agents.graph import (
2026-07-11T19:50:38.7251377Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7251669Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7252018Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7252562Z _________________ ERROR collecting tests/test_rate_limiting.py _________________
2026-07-11T19:50:38.7253274Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_rate_limiting.py'.
2026-07-11T19:50:38.7253959Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7254306Z Traceback:
2026-07-11T19:50:38.7254756Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7255356Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7255705Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7256004Z tests/test_rate_limiting.py:24: in <module>
2026-07-11T19:50:38.7256305Z     from tests.fakes import fake_current_user
2026-07-11T19:50:38.7256608Z tests/fakes.py:24: in <module>
2026-07-11T19:50:38.7256971Z     from app.agents.state import AgentState, Citation, Intent, PlannerDecision
2026-07-11T19:50:38.7257384Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7257658Z     from app.agents.graph import (
2026-07-11T19:50:38.7257923Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7258216Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7258567Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7258982Z _____________ ERROR collecting tests/test_session_authenticator.py _____________
2026-07-11T19:50:38.7259852Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_session_authenticator.py'.
2026-07-11T19:50:38.7260697Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7261030Z Traceback:
2026-07-11T19:50:38.7261483Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7262087Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7262432Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7262747Z tests/test_session_authenticator.py:17: in <module>
2026-07-11T19:50:38.7263095Z     from app.services.auth import SessionAuthenticator
2026-07-11T19:50:38.7263413Z app/services/auth.py:35: in <module>
2026-07-11T19:50:38.7263693Z     from app.security.oidc import OIDCClient
2026-07-11T19:50:38.7263983Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7264286Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7264627Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7265030Z ________________ ERROR collecting tests/test_session_memory.py _________________
2026-07-11T19:50:38.7265738Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_session_memory.py'.
2026-07-11T19:50:38.7266415Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7266763Z Traceback:
2026-07-11T19:50:38.7267211Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7267802Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7268148Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7268450Z tests/test_session_memory.py:20: in <module>
2026-07-11T19:50:38.7268753Z     from app.services.chat import ChatService
2026-07-11T19:50:38.7269059Z app/services/chat.py:42: in <module>
2026-07-11T19:50:38.7269356Z     from app.agents.state import AgentState, Citation
2026-07-11T19:50:38.7269665Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7269935Z     from app.agents.graph import (
2026-07-11T19:50:38.7270355Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7270651Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7270991Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7271523Z ____________________ ERROR collecting tests/test_sso_api.py ____________________
2026-07-11T19:50:38.7272202Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_sso_api.py'.
2026-07-11T19:50:38.7272853Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7273192Z Traceback:
2026-07-11T19:50:38.7273643Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7274247Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7274594Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7274882Z tests/test_sso_api.py:21: in <module>
2026-07-11T19:50:38.7275174Z     from app.api.auth import get_sso_auth_service
2026-07-11T19:50:38.7275471Z app/api/auth.py:25: in <module>
2026-07-11T19:50:38.7275717Z     from app.bootstrap import (
2026-07-11T19:50:38.7275969Z app/bootstrap.py:49: in <module>
2026-07-11T19:50:38.7276270Z     from app.security.oidc import AuthlibOIDCClient
2026-07-11T19:50:38.7276581Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7276888Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7277228Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7277625Z __________________ ERROR collecting tests/test_sso_service.py __________________
2026-07-11T19:50:38.7278439Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_sso_service.py'.
2026-07-11T19:50:38.7279112Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7279449Z Traceback:
2026-07-11T19:50:38.7279897Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7280648Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7281000Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7281296Z tests/test_sso_service.py:16: in <module>
2026-07-11T19:50:38.7281584Z     from app.services.auth import (
2026-07-11T19:50:38.7281846Z app/services/auth.py:35: in <module>
2026-07-11T19:50:38.7282123Z     from app.security.oidc import OIDCClient
2026-07-11T19:50:38.7282406Z app/security/oidc.py:33: in <module>
2026-07-11T19:50:38.7282704Z     from authlib.common.security import generate_token
2026-07-11T19:50:38.7283051Z E   ModuleNotFoundError: No module named 'authlib'
2026-07-11T19:50:38.7283450Z _________________ ERROR collecting tests/test_web_searcher.py __________________
2026-07-11T19:50:38.7284154Z ImportError while importing test module '/home/runner/work/career-coach-agent/career-coach-agent/backend/tests/test_web_searcher.py'.
2026-07-11T19:50:38.7284827Z Hint: make sure your test modules/packages have valid Python names.
2026-07-11T19:50:38.7285160Z Traceback:
2026-07-11T19:50:38.7285608Z ../../../../.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/importlib/__init__.py:126: in import_module
2026-07-11T19:50:38.7286199Z     return _bootstrap._gcd_import(name[level:], package, level)
2026-07-11T19:50:38.7286552Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
2026-07-11T19:50:38.7286844Z tests/test_web_searcher.py:28: in <module>
2026-07-11T19:50:38.7287145Z     from app.agents.graph import build_graph
2026-07-11T19:50:38.7287435Z app/agents/__init__.py:2: in <module>
2026-07-11T19:50:38.7287703Z     from app.agents.graph import (
2026-07-11T19:50:38.7287966Z app/agents/graph.py:72: in <module>
2026-07-11T19:50:38.7288261Z     from langgraph.graph import END, START, StateGraph
2026-07-11T19:50:38.7288610Z E   ModuleNotFoundError: No module named 'langgraph'
2026-07-11T19:50:38.7289017Z =========================== short test summary info ============================
2026-07-11T19:50:38.7289365Z ERROR tests/test_admin_feedback_api.py
2026-07-11T19:50:38.7289764Z ERROR tests/test_agent_graph.py
2026-07-11T19:50:38.8592435Z ERROR tests/test_agent_planner.py
2026-07-11T19:50:38.8592898Z ERROR tests/test_agent_responder.py
2026-07-11T19:50:38.8593266Z ERROR tests/test_agent_state.py
2026-07-11T19:50:38.8593597Z ERROR tests/test_auth_api.py
2026-07-11T19:50:38.8593925Z ERROR tests/test_auth_service.py
2026-07-11T19:50:38.8594263Z ERROR tests/test_authz_ratelimit_api.py
2026-07-11T19:50:38.8594623Z ERROR tests/test_chat_api.py
2026-07-11T19:50:38.8594959Z ERROR tests/test_chat_cancel.py
2026-07-11T19:50:38.8595289Z ERROR tests/test_chat_persistence.py
2026-07-11T19:50:38.8595632Z ERROR tests/test_chat_service.py
2026-07-11T19:50:38.8595951Z ERROR tests/test_guest_upgrade_api.py
2026-07-11T19:50:38.8596281Z ERROR tests/test_health.py
2026-07-11T19:50:38.8596579Z ERROR tests/test_input_guardrails.py
2026-07-11T19:50:38.8596903Z ERROR tests/test_message_id.py
2026-07-11T19:50:38.8597203Z ERROR tests/test_oidc_client.py
2026-07-11T19:50:38.8597536Z ERROR tests/test_p2_exit_verification.py
2026-07-11T19:50:38.8597896Z ERROR tests/test_p3_exit_verification.py
2026-07-11T19:50:38.8598265Z ERROR tests/test_p4_exit_verification.py
2026-07-11T19:50:38.8598622Z ERROR tests/test_rag_agent.py
2026-07-11T19:50:38.8598942Z ERROR tests/test_rate_limiting.py
2026-07-11T19:50:38.8599278Z ERROR tests/test_session_authenticator.py
2026-07-11T19:50:38.8599602Z ERROR tests/test_session_memory.py
2026-07-11T19:50:38.8599868Z ERROR tests/test_sso_api.py
2026-07-11T19:50:38.8600811Z ERROR tests/test_sso_service.py
2026-07-11T19:50:38.8601071Z ERROR tests/test_web_searcher.py
2026-07-11T19:50:38.8601437Z !!!!!!!!!!!!!!!!!!! Interrupted: 27 errors during collection !!!!!!!!!!!!!!!!!!!
2026-07-11T19:50:38.8601876Z ============================== 27 errors in 2.54s ==============================
2026-07-11T19:50:39.1518469Z ##[error]Process completed with exit code 2.
2026-07-11T19:50:39.1631733Z Node 20 is being deprecated. This workflow is running with Node 24 by default. If you need to temporarily use Node 20, you can set the ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION=true environment variable. For more information see: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/
2026-07-11T19:50:39.1632993Z Post job cleanup.
2026-07-11T19:50:39.2492625Z [command]/usr/bin/git version
2026-07-11T19:50:39.2538228Z git version 2.54.0
2026-07-11T19:50:39.2584182Z Temporarily overriding HOME='/home/runner/work/_temp/f6c96f21-f2d6-4d74-bc94-c5464b97b725' before making global git config changes
2026-07-11T19:50:39.2585559Z Adding repository directory to the temporary git global config as a safe directory
2026-07-11T19:50:39.2590687Z [command]/usr/bin/git config --global --add safe.directory /home/runner/work/career-coach-agent/career-coach-agent
2026-07-11T19:50:39.2631996Z [command]/usr/bin/git config --local --name-only --get-regexp core\.sshCommand
2026-07-11T19:50:39.2666634Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'core\.sshCommand' && git config --local --unset-all 'core.sshCommand' || :"
2026-07-11T19:50:39.2914601Z [command]/usr/bin/git config --local --name-only --get-regexp http\.https\:\/\/github\.com\/\.extraheader
2026-07-11T19:50:39.2942487Z http.https://github.com/.extraheader
2026-07-11T19:50:39.2954672Z [command]/usr/bin/git config --local --unset-all http.https://github.com/.extraheader
2026-07-11T19:50:39.2988884Z [command]/usr/bin/git submodule foreach --recursive sh -c "git config --local --name-only --get-regexp 'http\.https\:\/\/github\.com\/\.extraheader' && git config --local --unset-all 'http.https://github.com/.extraheader' || :"
2026-07-11T19:50:39.3257873Z [command]/usr/bin/git config --local --name-only --get-regexp ^includeIf\.gitdir:
2026-07-11T19:50:39.3295632Z [command]/usr/bin/git submodule foreach --recursive git config --local --show-origin --name-only --get-regexp remote.origin.url
2026-07-11T19:50:39.3701013Z Print service container logs: 04d11f3417ce45de9b5e1794ab2c5948_pgvectorpgvectorpg16_89083a
2026-07-11T19:50:39.3705779Z ##[command]/usr/bin/docker logs --details e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:39.3836825Z  initdb: warning: enabling "trust" authentication for local connections
2026-07-11T19:50:39.3838150Z  initdb: hint: You can change this by editing pg_hba.conf or using the option -A, or --auth-local and --auth-host, the next time you run initdb.
2026-07-11T19:50:39.3839835Z  2026-07-11 19:50:06.583 UTC [1] LOG:  starting PostgreSQL 16.14 (Debian 16.14-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
2026-07-11T19:50:39.3851590Z  2026-07-11 19:50:06.584 UTC [1] LOG:  listening on IPv4 address "0.0.0.0", port 5432
2026-07-11T19:50:39.3852603Z  2026-07-11 19:50:06.584 UTC [1] LOG:  listening on IPv6 address "::", port 5432
2026-07-11T19:50:39.3853522Z  2026-07-11 19:50:06.585 UTC [1] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
2026-07-11T19:50:39.3854148Z  2026-07-11 19:50:06.588 UTC [65] LOG:  database system was shut down at 2026-07-11 19:50:06 UTC
2026-07-11T19:50:39.3854660Z  2026-07-11 19:50:06.592 UTC [1] LOG:  database system is ready to accept connections
2026-07-11T19:50:39.3855169Z  The files belonging to this database system will be owned by user "postgres".
2026-07-11T19:50:39.3855642Z  This user must also own the server process.
2026-07-11T19:50:39.3855913Z  
2026-07-11T19:50:39.3856185Z  The database cluster will be initialized with locale "en_US.utf8".
2026-07-11T19:50:39.3856863Z  The default database encoding has accordingly been set to "UTF8".
2026-07-11T19:50:39.3857294Z  The default text search configuration will be set to "english".
2026-07-11T19:50:39.3857617Z  
2026-07-11T19:50:39.3857810Z  Data page checksums are disabled.
2026-07-11T19:50:39.3858053Z  
2026-07-11T19:50:39.3858347Z  fixing permissions on existing directory /var/lib/postgresql/data ... ok
2026-07-11T19:50:39.3858746Z  creating subdirectories ... ok
2026-07-11T19:50:39.3859067Z  selecting dynamic shared memory implementation ... posix
2026-07-11T19:50:39.3859414Z  selecting default max_connections ... 100
2026-07-11T19:50:39.3859702Z  selecting default shared_buffers ... 128MB
2026-07-11T19:50:39.3860235Z  selecting default time zone ... Etc/UTC
2026-07-11T19:50:39.3860623Z  creating configuration files ... ok
2026-07-11T19:50:39.3860893Z  running bootstrap script ... ok
2026-07-11T19:50:39.3861400Z  performing post-bootstrap initialization ... ok
2026-07-11T19:50:39.3861930Z  syncing data to disk ... ok
2026-07-11T19:50:39.3862294Z  
2026-07-11T19:50:39.3862461Z  
2026-07-11T19:50:39.3862686Z  Success. You can now start the database server using:
2026-07-11T19:50:39.3862973Z  
2026-07-11T19:50:39.3863198Z      pg_ctl -D /var/lib/postgresql/data -l logfile start
2026-07-11T19:50:39.3863494Z  
2026-07-11T19:50:39.3864170Z  waiting for server to start....2026-07-11 19:50:06.273 UTC [49] LOG:  starting PostgreSQL 16.14 (Debian 16.14-1.pgdg12+1) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
2026-07-11T19:50:39.3865094Z  2026-07-11 19:50:06.274 UTC [49] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
2026-07-11T19:50:39.3865653Z  2026-07-11 19:50:06.276 UTC [52] LOG:  database system was shut down at 2026-07-11 19:50:06 UTC
2026-07-11T19:50:39.3866173Z  2026-07-11 19:50:06.280 UTC [49] LOG:  database system is ready to accept connections
2026-07-11T19:50:39.3866545Z   done
2026-07-11T19:50:39.3866722Z  server started
2026-07-11T19:50:39.3866920Z  CREATE DATABASE
2026-07-11T19:50:39.3867105Z  
2026-07-11T19:50:39.3867271Z  
2026-07-11T19:50:39.3867596Z  /usr/local/bin/docker-entrypoint.sh: ignoring /docker-entrypoint-initdb.d/*
2026-07-11T19:50:39.3867997Z  
2026-07-11T19:50:39.3868359Z  waiting for server to shut down...2026-07-11 19:50:06.459 UTC [49] LOG:  received fast shutdown request
2026-07-11T19:50:39.3869114Z  .2026-07-11 19:50:06.460 UTC [49] LOG:  aborting any active transactions
2026-07-11T19:50:39.3869720Z  2026-07-11 19:50:06.462 UTC [49] LOG:  background worker "logical replication launcher" (PID 55) exited with exit code 1
2026-07-11T19:50:39.3870583Z  2026-07-11 19:50:06.462 UTC [50] LOG:  shutting down
2026-07-11T19:50:39.3870979Z  2026-07-11 19:50:06.462 UTC [50] LOG:  checkpoint starting: shutdown immediate
2026-07-11T19:50:39.3872080Z  2026-07-11 19:50:06.477 UTC [50] LOG:  checkpoint complete: wrote 922 buffers (5.6%); 0 WAL file(s) added, 0 removed, 0 recycled; write=0.011 s, sync=0.002 s, total=0.015 s; sync files=301, longest=0.001 s, average=0.001 s; distance=4255 kB, estimate=4255 kB; lsn=0/1912120, redo lsn=0/1912120
2026-07-11T19:50:39.3873156Z  2026-07-11 19:50:06.483 UTC [49] LOG:  database system is shut down
2026-07-11T19:50:39.3873498Z   done
2026-07-11T19:50:39.3873688Z  server stopped
2026-07-11T19:50:39.3873885Z  
2026-07-11T19:50:39.3874127Z  PostgreSQL init process complete; ready for start up.
2026-07-11T19:50:39.3874440Z  
2026-07-11T19:50:39.3879644Z Stop and remove container: 04d11f3417ce45de9b5e1794ab2c5948_pgvectorpgvectorpg16_89083a
2026-07-11T19:50:39.3885160Z ##[command]/usr/bin/docker rm --force e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:40.0443876Z e522143f0057aabca51e22b4c5d9f742609b38f2ba4aa3d43987b13b5a6fc633
2026-07-11T19:50:40.0476505Z Remove container network: github_network_48079045eec94823bfd27d4dad02e27d
2026-07-11T19:50:40.0481025Z ##[command]/usr/bin/docker network rm github_network_48079045eec94823bfd27d4dad02e27d
2026-07-11T19:50:40.1875779Z github_network_48079045eec94823bfd27d4dad02e27d
2026-07-11T19:50:40.1945073Z Cleaning up orphan processes
2026-07-11T19:50:40.2362803Z ##[warning]Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/checkout@v4, astral-sh/setup-uv@v5. For more information see: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/