# nix/slave-agent.nix — Overridable slave-agent package
#
# callPackage auto-wires nixpkgs args; flake inputs are passed explicitly.
# Users override via:
#   pkgs.slave-agent.override { extraPythonPackages = [...]; }
#   pkgs.slave-agent.override { extraDependencyGroups = [ "google-meet" ]; }
# Both extras add to what the package ships. The shipped groups live in
# defaultDependencyGroups (set by packages.nix for `full`/`messaging`), so a
# plain override of the extras never drops them.
{
  lib,
  stdenv,
  makeWrapper,
  writeText,
  callPackage,
  runCommand,
  electron,
  git,
  openssh,
  ffmpeg-headless,

  # for pm
  writeShellApplication,

  # linux-only deps
  wl-clipboard,
  xclip,

  # linux-only dev deps
  cage,

  # Flake inputs — passed explicitly by packages.nix and overlays.nix
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  # nix/pm-packages.nix output: every pm/lock.json pin as a derivation.
  pmPackages,
  # Locked git revision of the flake source — embedded so banner.py can
  # check for updates without needing a local .git directory. Null for
  # impure / dirty builds where flakes can't determine a rev.
  rev ? null,
  branch ? null,
  dirty ? false,
  lastModified ? null,
  # Overridable parameters
  version ? "0.0.0",
  distance ? 0,
  extraPythonPackages ? [ ],
  # The optional groups this variant ships; packages.nix owns the lists.
  defaultDependencyGroups ? [ ],
  # The user's additions on top of defaultDependencyGroups.
  extraDependencyGroups ? [ ],
}:
let
  # One owner (pythonLock.nix) reads pm/lock.json and selects the matching
  # nixpkgs interpreter. Everything Python-shaped below derives from it.
  pythonLock = callPackage ./pythonLock.nix { };
  python = pythonLock.interpreter;

  packageDependencyGroups = defaultDependencyGroups ++ extraDependencyGroups;

  # Install stamp values — written to install-stamp.json so the Python
  # runtime (CLI, TUI) reads one file instead of env vars or .git probes.
  stampDistance =
    if builtins.isInt distance && distance >= 0 then
      distance
    else
      throw "distance must be a non-negative integer";
  stampDisplayVersion =
    if stampDistance > 0 && rev != null then
      "${version}+${toString stampDistance}.g${builtins.substring 0 7 rev}"
    else if stampDistance > 0 then
      throw "a non-zero distance requires an exact revision"
    else
      version;

  # CLI and Electron consume the same provenance and update owner.
  installStampFile = writeText "slave-install-stamp.json" (
    builtins.toJSON {
      schemaVersion = 2;
      commit = rev;
      commitDate = lastModified;
      inherit branch dirty;
      builtAt = null;
      baseVersion = version;
      displayVersion = stampDisplayVersion;
      distance = stampDistance;
      source = "nix";
      distribution = "nix";
      pmRuntime = toString pmRuntime;
      updateMechanism = "external";
      payload = "bootstrap";
      tag = null;
    }
  );

  mkSlaveVenv =
    groups:
    callPackage ./python.nix {
      inherit uv2nix pyproject-nix pyproject-build-systems;
      pythonSrc = slaveNpmLib.pythonSrc;
      # Deduplicated so naming a group the variant already ships leaves the
      # venv derivation unchanged.
      dependency-groups = lib.unique ([ "all" ] ++ groups);
    };

  slaveVenv = (mkSlaveVenv packageDependencyGroups).venv;

  pmRuntime = callPackage ./pm-runtime.nix {
    inherit uv2nix pyproject-nix pyproject-build-systems;
  };

  # Icons render on the runtime venv: Pillow and resvg-py are core dependencies.
  generatedIcons = callPackage ./icons.nix {
    inherit (mkSlaveVenv [ ]) venv;
  };

  slaveNpmLib = callPackage ./lib.nix {
    inherit pmPackages;
  };

  slaveTui = callPackage ./tui.nix {
    inherit slaveNpmLib;
  };

  slaveWeb = callPackage ./web.nix {
    inherit slaveNpmLib generatedIcons;
  };

  # The store is read-only, so the Webapp is built here and never by `slave webapp`.
  slaveWebapp = callPackage ./webapp.nix {
    inherit slaveNpmLib;
  };

  bundledSkills = lib.cleanSourceWith {
    src = ../skills;
    filter = path: _type: !(lib.hasInfix "/index-cache/" path) && !(lib.hasInfix "/__pycache__/" path);
  };

  # Optional skills are NOT in the wheel (pythonSrc excludes them, see
  # lib.nix) — the wrapper exposes them via SLAVE_OPTIONAL_SKILLS, the
  # same mechanism Homebrew packaging uses.
  bundledOptionalSkills = lib.cleanSourceWith {
    src = ../optional-skills;
    filter = path: _type: !(lib.hasInfix "/index-cache/" path) && !(lib.hasInfix "/__pycache__/" path);
  };

  # Import bundled plugins (memory, context_engine, platforms/*).  Keeping
  # them out of the Python site-packages keeps import semantics identical
  # to a dev checkout — the loader reads them from SLAVE_BUNDLED_PLUGINS.
  bundledPlugins = lib.cleanSourceWith {
    src = ../plugins;
    filter = path: _type: !(lib.hasInfix "/__pycache__/" path);
  };

  # i18n locale catalogs (locales/*.yaml). Shipped into the store and pointed
  # at by SLAVE_BUNDLED_LOCALES so the wrapped binary always resolves human
  # strings instead of raw i18n keys (#23943 / #27632 / #35374).
  bundledLocales = lib.cleanSource ../locales;

  # Shipped MCP catalog (optional-mcps/<name>/manifest.yaml). Same bare-data-dir
  # case as locales: not a Python package, so it's symlinked into the store and
  # exposed via SLAVE_OPTIONAL_MCPS.
  bundledOptionalMcps = lib.cleanSourceWith {
    src = ../optional-mcps;
    filter = path: _type: !(lib.hasInfix "/__pycache__/" path);
  };

  # Tools come from pm/lock.json, the same builds `slave pm install`
  # provisions elsewhere. git and openssh are nixpkgs': the lock pins them for
  # win32 only. slaveNpmLib.nodejs is the pinned node with the pinned npm.
  runtimeDeps = [
    slaveNpmLib.nodejs
    pmPackages.ripgrep
    pmPackages.ffmpeg
    git
    openssh
  ]
  # pm's macOS ffmpeg is a single binary with no ffprobe, which transcription
  # needs to measure duration before splitting long recordings. Only ffprobe
  # is linked, so `ffmpeg` on PATH stays the pinned build.
  ++ lib.optionals stdenv.hostPlatform.isDarwin [
    (runCommand "ffprobe-${ffmpeg-headless.version}" { } ''
      mkdir -p $out/bin
      ln -s ${lib.getBin ffmpeg-headless}/bin/ffprobe $out/bin/ffprobe
    '')
  ]
  ++ lib.optionals stdenv.hostPlatform.isLinux [
    wl-clipboard
    xclip
  ];

  runtimePath = lib.makeBinPath runtimeDeps;

  sitePackagesPath = python.sitePackages;

  # Only the offline assembler's import closure. A frontend or catalog edit
  # must not change this source, and no build output is read during evaluation.
  agentBuilderSrc = lib.fileset.toSource {
    root = ./..;
    fileset = lib.fileset.unions [
      ../scripts/build/agent.py
      ../scripts/build/inputs.py
      ../scripts/build/launchers.py
    ];
  };

  agentInputsFile = writeText "slave-agent-inputs.json" (
    builtins.toJSON {
      project = "${../pyproject.toml}";
      code = "${slaveVenv}/${sitePackagesPath}";
      repo = "share/slave-agent";
      placement = "references";
      target = "${if stdenv.hostPlatform.isDarwin then "darwin" else "linux"}-${
        if stdenv.hostPlatform.isAarch64 then "arm64" else "x64"
      }";
      python = "${slaveVenv}/bin/python3";
      site_packages = "${slaveVenv}/${sitePackagesPath}";
      environment = toString slaveVenv;
      pm_runtime = toString pmRuntime;
      command_dir = "${slaveVenv}/bin";
      resources = {
        skills = toString bundledSkills;
        optional-skills = toString bundledOptionalSkills;
        plugins = toString bundledPlugins;
        locales = toString bundledLocales;
        optional-mcps = toString bundledOptionalMcps;
      };
      frontends = {
        tui = "${slaveTui}/lib/slave-tui";
        web = toString slaveWeb;
        webapp = toString slaveWebapp;
      };
      ref = if dirty then null else rev;
      stamp = toString installStampFile;
      env = {
        SLAVE_NODE = lib.getExe slaveNpmLib.nodejs;
      }
      // lib.optionalAttrs (rev != null && !dirty) {
        SLAVE_REVISION = rev;
      };
    }
  );

  # Walk propagatedBuildInputs to include transitive Python deps in PYTHONPATH.
  # Without this, a plugin listing e.g. requests as a dep would fail at runtime
  # if requests isn't already in the sealed uv2nix venv.
  allExtraPythonPackages = python.pkgs.requiredPythonModules extraPythonPackages;

  pythonPath = lib.makeSearchPath sitePackagesPath allExtraPythonPackages;

  checkPackageCollisions = ''
    import pathlib, sys, re

    def canonical(name):
        return re.sub(r'[-_.]+', '-', name).lower()

    # Collect core venv package names
    core = set()
    venv_sp = pathlib.Path('${slaveVenv}/${sitePackagesPath}')
    for di in venv_sp.glob('*.dist-info'):
        meta = di / 'METADATA'
        if meta.exists():
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    core.add(canonical(line.split(':', 1)[1].strip()))
                    break

    # Check each extra package for collisions
    extras_dirs = [${lib.concatMapStringsSep ", " (p: "'${toString p}'") allExtraPythonPackages}]
    for edir in extras_dirs:
        sp = pathlib.Path(edir) / '${sitePackagesPath}'
        if not sp.exists():
            continue
        for di in sp.glob('*.dist-info'):
            meta = di / 'METADATA'
            if not meta.exists():
                continue
            for line in meta.read_text().splitlines():
                if line.startswith('Name:'):
                    pkg = canonical(line.split(':', 1)[1].strip())
                    if pkg in core:
                        print(f'ERROR: plugin package \"{pkg}\" collides with a package in slave sealed venv', file=sys.stderr)
                        print(f'  from: {di}', file=sys.stderr)
                        print(f'  Remove this dependency from extraPythonPackages.', file=sys.stderr)
                        sys.exit(1)
                    break

    print('No collisions found.')
  '';
in
stdenv.mkDerivation (finalAttrs: {
  pname = "slave-agent";
  inherit version;

  dontUnpack = true;
  dontBuild = true;
  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    # uv2nix owns Python code and dependencies. The shared assembler only
    # links resources and emits the derived command/environment description.
    PYTHONPATH=${agentBuilderSrc} ${python}/bin/python3 -m scripts.build.agent \
      --inputs ${agentInputsFile} --out "$out"

    # Native wrappers retain Nix's PATH/PYTHONPATH policies. Names, executable
    # sources and resource bindings come from the builder, not another table.
    makeAgentWrapper() {
      local source="$1" destination="$2"
      shift 2
      makeWrapper "$source" "$out/$destination" "$@" \
        --suffix PATH : "${runtimePath}" \
        --set-default SLAVE_BIN "$out/bin/slave"${
          lib.optionalString (
            extraPythonPackages != [ ]
          ) " \\\n        --suffix PYTHONPATH : \"${pythonPath}\""
        }
    }
    ${python}/bin/python3 - "$out/command-map.json" > "$TMPDIR/agent-wrappers.sh" <<'PY'
    import json, shlex, sys

    with open(sys.argv[1]) as handle:
        description = json.load(handle)
    env = [arg for key, value in sorted(description["env"].items())
           for arg in ("--set", key, value)]
    for command in description["commands"].values():
        print(shlex.join(["makeAgentWrapper", command["source"], command["destination"], *env]))
    PY
    source "$TMPDIR/agent-wrappers.sh"

    ${lib.optionalString (extraPythonPackages != [ ]) ''
      echo "=== Checking for plugin/core package collisions ==="
      ${slaveVenv}/bin/python3 -c "${checkPackageCollisions}"
      echo "=== No collisions ==="
    ''}

    runHook postInstall
  '';

  passthru =
    let
      # uv2nix builds the editable venv against the nixpkgs interpreter (it
      # cannot build against a tarball one); devVenv re-homes it onto the
      # interpreter pm/lock.json pins.
      devPython = (mkSlaveVenv (packageDependencyGroups ++ [ "dev" ])).editableVenv;
      pmPython = pmPackages.python;

      # A real venv: pyvenv.cfg's `home` is the pinned interpreter and its
      # site-packages are devPython's, so `.pth` files (the editable checkout)
      # load and nothing depends on the caller's PYTHONPATH. Console scripts
      # are re-shebanged onto it so `pytest` and `python -m pytest` agree.
      # The project's own commands (`slave`, ...) go to libexec, off PATH, so
      # the dev shell never hides the installed slave-agent; `slave-checkout` runs them.
      projectCommands = builtins.attrNames (lib.importTOML ../pyproject.toml).project.scripts;
      devVenv = runCommand "slave-agent-dev-venv" { } ''
        mkdir -p $out/bin $out/libexec/slave-checkout $out/lib/python${python.pythonVersion}
        ln -s ${devPython}/${sitePackagesPath} $out/${sitePackagesPath}
        cat > $out/pyvenv.cfg <<EOF
        home = ${pmPython}/bin
        include-system-site-packages = false
        version = ${lib.head (lib.splitString "+" pmPython.version)}
        EOF
        for name in python python3 python${python.pythonVersion}; do
          ln -s ${pmPython}/bin/python3 $out/bin/$name
        done
        # Every other command carries over: Python scripts re-shebanged onto
        # this venv, native ones (ruff, ty) linked as-is. The activate scripts
        # and devPython's own interpreter links would point back at devPython.
        devInterpreter=$(readlink -f ${devPython}/bin/python3)
        for script in ${devPython}/bin/*; do
          name=$(basename "$script")
          [ -e "$out/bin/$name" ] && continue
          case "$name" in activate*|Activate*) continue ;; esac
          [ "$(readlink -f "$script")" = "$devInterpreter" ] && continue
          case " ${lib.concatStringsSep " " projectCommands} " in
            *" $name "*) dir=$out/libexec/slave-checkout ;;
            *) dir=$out/bin ;;
          esac
          if head -n1 "$script" | grep -q '^#!.*python'; then
            { echo "#!$out/bin/python3"; tail -n +2 "$script"; } > "$dir/$name"
            chmod +x "$dir/$name"
          else
            ln -s "$script" "$dir/$name"
          fi
        done
        # The libexec name stays `slave`: process identity and relaunch read argv[0].
        printf '#!/bin/sh\nexec %s "$@"\n' "$out/libexec/slave-checkout/slave" > $out/bin/slave-checkout
        chmod +x $out/bin/slave-checkout
      '';

      pm = writeShellApplication {
        name = "pm";
        text = ''
          cd "$(git rev-parse --show-toplevel)"
          exec ${devVenv}/bin/python3 -m pm.cli "$@"
        '';
      };
    in
    {
      inherit
        slaveTui
        slaveWeb
        slaveWebapp
        slaveNpmLib
        slaveVenv
        agentBuilderSrc
        agentInputsFile
        installStampFile
        pmRuntime
        python
        devPython
        devVenv
        pmPython
        ;

      # `slaveDesktop` references `finalAttrs.finalPackage` (this whole
      # derivation, after all overrides are applied) so the desktop wrapper
      # can pin its `slave` command via SLAVE_DESKTOP_SLAVE. The
      # deployment override then picks up the fully wrapped
      # `slave` binary — venv with all deps, bundled skills/plugins,
      # runtime PATH (ripgrep/git/ffmpeg/etc).  No re-implementation
      # of the agent resolution in the desktop wrapper.
      slaveDesktop = callPackage ./desktop.nix {
        inherit
          slaveNpmLib
          electron
          installStampFile
          generatedIcons
          ;
        python3 = python;
        slaveAgent = finalAttrs.finalPackage;
      };

      devShellHook = ''
        export SLAVE_PYTHON=${devVenv}/bin/python3
        # `uv run --active --no-sync` reuses this venv instead of creating .venv.
        export VIRTUAL_ENV=${devVenv}
      '';

      devDeps =
        runtimeDeps
        ++ [
          # The pnpm the builds install with: the pm/lock.json pin.
          slaveNpmLib.pnpm
          pmPackages.uv
          devVenv
          pm
        ]
        ++ lib.optionals stdenv.hostPlatform.isLinux [
          cage # for running e2e tests without popping windows
        ];
    };

  meta = with lib; {
    description = "AI agent with advanced tool-calling capabilities";
    homepage = "https://github.com/NousResearch/hermes-agent";
    mainProgram = "slave";
    license = licenses.mit;
    platforms = platforms.unix;
  };
})
