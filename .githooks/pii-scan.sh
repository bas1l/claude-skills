#!/bin/sh
# Shared personal-data scanner for the pre-commit hook, the pre-push hook and CI.
# Public repository: no real email addresses, no absolute machine paths.
#
#   pii-scan.sh staged              added lines of the staged diff (+ local denylist)
#   pii-scan.sh tree [--local]      every tracked text file (--local adds the denylist)
#   pii-scan.sh ident "<ident>"     one "Name <email>" identity must be a noreply address
#   pii-scan.sh commits <rev>...    author/committer emails of the commits in <rev>...
#
# A line containing the marker "pii-allow" is skipped by the line scans.
# Exit status 0 = clean, 1 = findings.

root=$(git rev-parse --show-toplevel) || exit 2
cd "$root" || exit 2

# Emails that may appear anywhere; everything else is a finding.
OK_EMAIL='(@users\.noreply\.github\.com|^noreply@github\.com|^noreply@anthropic\.com|^git@github\.com|@example\.(com|org)|\.invalid)$'
# Emails allowed as a commit identity.
OK_IDENT='(@users\.noreply\.github\.com|^noreply@github\.com)$'

# Fixed-string terms: the global git identity email plus .githooks/denylist.local.
build_terms() {
    f=$1
    : > "$f"
    g=$(git config --global user.email 2>/dev/null)
    [ -n "$g" ] && printf '%s\n' "$g" >> "$f"
    if [ -f .githooks/denylist.local ]; then
        sed -e 's/\r$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' .githooks/denylist.local >> "$f"
    fi
}

# stdin: path:line:text records. stderr: findings. Status 1 when any.
scan_lines() {
    export OK_EMAIL; awk -v termsfile="$1" -v okeenv=OK_EMAIL '
    BEGIN {
        okemail = ENVIRON[okeenv]
        n = 0
        if (termsfile != "") {
            while ((getline t < termsfile) > 0) if (t != "") terms[++n] = tolower(t)
            close(termsfile)
        }
    }
    {
        if (!match($0, /^[^:]*:[0-9]+:/)) next
        loc = substr($0, 1, RLENGTH - 1)
        text = substr($0, RLENGTH + 1)
        if (index(text, "pii-allow")) next
        low = tolower(text)
        for (i = 1; i <= n; i++)
            if (index(low, terms[i])) report(loc, "denylisted term", terms[i])
        rest = text
        while (match(rest, /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]+/)) {
            e = substr(rest, RSTART, RLENGTH)
            rest = substr(rest, RSTART + RLENGTH)
            if (tolower(e) !~ okemail) report(loc, "email address", e)
        }
        rest = text
        while (match(rest, /(^|[^A-Za-z0-9_])[A-Za-z]:[\\/]+/)) {
            m = substr(rest, RSTART, RLENGTH)
            after = tolower(substr(rest, RSTART + RLENGTH))
            rest = substr(rest, RSTART + RLENGTH)
            if (after ~ /^(program files|windows|users[\\/]+(<|someone|x|public|default)|<|someone|x([\\/]|$))/) continue
            report(loc, "absolute drive path", m substr(after, 1, 20))
        }
        rest = text
        while (match(rest, /(^|[^A-Za-z0-9_.-])\/(Users|home)\/[A-Za-z0-9_.-]+/)) {
            m = substr(rest, RSTART, RLENGTH)
            rest = substr(rest, RSTART + RLENGTH)
            sub(/^[^\/]/, "", m)
            nm = m; sub(/^\/[A-Za-z]+\//, "", nm)
            if (tolower(nm) ~ /^(someone|x|user|username|name)$/) continue
            report(loc, "absolute home path", m)
        }
    }
    function report(loc, kind, what) {
        printf "pii-scan: %s: %s: %s\n", loc, kind, what > "/dev/stderr"
        bad = 1
    }
    END { exit bad ? 1 : 0 }'
}

# Added lines of a diff on stdin -> path:line:text records.
added_lines() {
    awk '
    /^\+\+\+ / { f = substr($0, 7); next }
    /^@@ / { s = $3; sub(/^\+/, "", s); sub(/,.*/, "", s); ln = s + 0; next }
    /^\+/ { print f ":" ln ":" substr($0, 2); ln++ }'
}

ident_ok() {  # $1 = label, $2 = "Name <email>"
    em=$(printf '%s' "$2" | sed -n 's/.*<\([^>]*\)>.*/\1/p')
    if ! printf '%s' "$em" | grep -E -i -q "$OK_IDENT"; then
        echo "pii-scan: $1 email '$em' is not a noreply address" >&2
        return 1
    fi
}

mode=$1; shift
tmp=$(mktemp) || exit 2
trap 'rm -f "$tmp"' EXIT
rc=0

case $mode in
staged)
    build_terms "$tmp"
    git -c core.quotepath=off diff --cached -U0 --no-color --no-ext-diff --diff-filter=ACMR \
        | added_lines | scan_lines "$tmp" || rc=1
    ;;
tree)
    : > "$tmp"
    [ "$1" = "--local" ] && build_terms "$tmp"
    git -c core.quotepath=off grep -I -n --no-color -e '' | scan_lines "$tmp" || rc=1
    ;;
ident)
    ident_ok identity "$1" || rc=1
    ;;
commits)
    git log --format='%H %an <%ae> %cn <%ce>' "$@" > "$tmp" || exit 2
    while read -r h rest; do
        a=${rest%%> *}'>'
        c=${rest#*> }
        ident_ok "author of $h" "$a" || rc=1
        ident_ok "committer of $h" "$c" || rc=1
    done < "$tmp"
    ;;
*)
    echo "usage: pii-scan.sh staged | tree [--local] | ident <ident> | commits <rev>..." >&2
    exit 2
    ;;
esac

[ $rc -ne 0 ] && echo "pii-scan: blocked. Remove the data, or mark a deliberate line with pii-allow." >&2
exit $rc
