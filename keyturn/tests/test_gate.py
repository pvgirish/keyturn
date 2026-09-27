import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import gate  # noqa: E402

OLD = "mastodon"
UL = '"mastodon" "md5aaaa"\n"pgbouncer" "md5bbbb"\n'


def cmd(c):
    return gate.classify("execute_command", {"command": c}, OLD, ["/home/u/.keyturn"], None, UL)


def fed(tool, **inp):
    return gate.classify(tool, inp, OLD, ["/home/u/.keyturn"], None, UL)


def kind(c):
    return c["kind"] if c else None


class Sql(unittest.TestCase):
    def test_retire_forms(self):
        for c in ("docker exec db psql -U postgres -c \"ALTER ROLE mastodon NOLOGIN;\"",
                  "psql -c 'DROP ROLE IF EXISTS mastodon'", "psql -c 'drop user other, mastodon'",
                  "psql -c 'ALTER ROLE mastodon RENAME TO old_m'", "psql -c \"ALTER ROLE mastodon VALID UNTIL '2020-01-01'\""):
            self.assertEqual(kind(cmd(c)), "retire_old_role", c)

    def test_in_place_change_is_its_own_kind(self):
        for c in ("psql -c \"ALTER USER mastodon WITH PASSWORD 'x';\"", "psql -c \"alter role \\\"mastodon\\\" encrypted password 'x'\"",
                  "psql -U postgres -c '\\password mastodon'"):
            self.assertEqual(kind(cmd(c)), "change_old_password", c)

    def test_sql_file(self):
        c = gate.classify("execute_command", {"command": "psql -f rotate.sql"}, OLD, [], ["ALTER ROLE mastodon NOLOGIN;"], UL)
        self.assertEqual(kind(c), "retire_old_role")

    def test_more_sql_forms(self):
        self.assertEqual(gate.sql_file_args("docker exec -i db psql -U postgres < rotate.sql"), ["rotate.sql"])
        self.assertEqual(kind(cmd("docker exec -i db psql -U postgres <<'SQL'\nALTER ROLE mastodon PASSWORD 'x';\nSQL")), "change_old_password")
        self.assertEqual(kind(cmd("docker compose exec web bin/rails runner \"ActiveRecord::Base.connection.execute(%q{ALTER ROLE mastodon NOLOGIN})\"")),
                         "retire_old_role")

    def test_known_gaps_stay_documented(self):
        # not covered on purpose (see V0.2-TEST-REPORT.md): script files, python writes, podman
        for c in ("bash rotate.sh", "python3 -c \"open('pgbouncer/userlist.txt','w').write('')\"", "podman restart web"):
            self.assertIsNone(cmd(c), c)

    def test_not_covered(self):
        for c in ("psql -c \"CREATE ROLE mastodon_v2 LOGIN PASSWORD 'x'; GRANT mastodon TO mastodon_v2;\"",
                  "psql -c \"ALTER ROLE mastodon_v2 WITH PASSWORD 'x'\"", "psql -d mastodon_production -c 'select 1'",
                  "cat ~/mastodon-ops/pgbouncer/userlist.txt", "grep -n mastodon .env.production",
                  "printf '\"mastodon_v2\" \"md5cc\"\\n' >> pgbouncer/userlist.txt",
                  "psql -c \"select pg_terminate_backend(pid) from pg_stat_activity where usename='mastodon'\"",
                  "psql -c 'REASSIGN OWNED BY mastodon TO mastodon_v2'", "docker compose ps", "docker compose logs web",
                  "grep RELOAD notes.md"):
            self.assertIsNone(cmd(c), c)


class Activation(unittest.TestCase):
    def test_activation_forms(self):
        for c in ("docker compose up -d --force-recreate web sidekiq streaming", "docker restart web",
                  "docker compose restart pgbouncer", "docker kill --signal=SIGHUP pgbouncer", "docker kill -s HUP pgbouncer",
                  "docker exec -e PGPASSWORD=x db psql -h pgbouncer -p 6432 -U pgbouncer pgbouncer -c 'RELOAD'",
                  "docker compose up -d"):
            self.assertEqual(kind(cmd(c)), "activate", c)

    def test_more_activation_forms(self):
        for c in ("docker compose restart", "docker exec pgbouncer kill -HUP 1", "docker exec pgbouncer kill -1 1"):
            self.assertEqual(kind(cmd(c)), "activate", c)
        for c in ("docker compose restart db", "docker exec pgbouncer ps", "docker compose logs --tail 5"):
            self.assertIsNone(cmd(c), c)

    def test_stop_and_down_forms(self):
        for c in ("docker stop web", "docker compose stop web", "docker compose down", "docker compose down -v",
                  "docker compose stop", "docker rm -f pgbouncer"):
            self.assertEqual(kind(cmd(c)), "activate", c)
        for c in ("docker compose stop db", "docker stop redis"):
            self.assertIsNone(cmd(c), c)

    def test_db_only_up_not_activation(self):
        self.assertIsNone(cmd("docker compose up -d db redis"))


class Userlist(unittest.TestCase):
    def test_sed_delete(self):
        self.assertEqual(kind(cmd("sed -i '' '/\"mastodon\"/d' pgbouncer/userlist.txt")), "retire_old_role")

    def test_grep_v(self):
        self.assertEqual(kind(cmd("grep -v '^\"mastodon\"' pgbouncer/userlist.txt > t && mv t pgbouncer/userlist.txt")), "retire_old_role")

    def test_sed_hash_change_is_change(self):
        self.assertEqual(kind(cmd("sed -i 's/\"mastodon\" \"md5aaaa\"/\"mastodon\" \"md5cccc\"/' pgbouncer/userlist.txt")), "change_old_password")

    def test_full_rewrite_without_old(self):
        self.assertEqual(kind(fed("write_file", path="pgbouncer/userlist.txt", content='"mastodon_v2" "md5cc"\n"pgbouncer" "md5bbbb"\n')), "retire_old_role")

    def test_full_rewrite_keeping_old_unchanged(self):
        self.assertIsNone(fed("write_file", path="pgbouncer/userlist.txt", content=UL + '"mastodon_v2" "md5cc"\n'))

    def test_full_rewrite_changing_old_hash(self):
        self.assertEqual(kind(fed("write_file", path="pgbouncer/userlist.txt", content='"mastodon" "md5cccc"\n"pgbouncer" "md5bbbb"\n')), "change_old_password")

    def test_apply_diff_hash_change(self):
        d = '<<<<<<< SEARCH\n"mastodon" "md5aaaa"\n=======\n"mastodon" "md5cccc"\n>>>>>>> REPLACE'
        self.assertEqual(kind(fed("apply_diff", path="pgbouncer/userlist.txt", diff=d)), "change_old_password")

    def test_apply_diff_removal(self):
        d = '<<<<<<< SEARCH\n"mastodon" "md5aaaa"\n"pgbouncer" "md5bbbb"\n=======\n"pgbouncer" "md5bbbb"\n>>>>>>> REPLACE'
        self.assertEqual(kind(fed("apply_diff", path="pgbouncer/userlist.txt", diff=d)), "retire_old_role")

    def test_search_and_replace(self):
        self.assertEqual(kind(fed("search_and_replace", path="pgbouncer/userlist.txt", search='"mastodon" "md5aaaa"\n', replace="")), "retire_old_role")

    def test_insert_new_user_line_is_not_covered(self):
        # v0.1 false positive (P2 run 1): inserting a line was treated as a full rewrite
        self.assertIsNone(fed("insert_content", path="pgbouncer/userlist.txt", line=1, content='"mastodon_v2" "md5cc"\n'))

    def test_copy_over_userlist(self):
        def c(cmd_, text):
            return kind(gate.classify("execute_command", {"command": cmd_}, OLD, [], None, UL, text))
        self.assertEqual(c("cp /tmp/ul pgbouncer/userlist.txt", '"mastodon_v2" "md5cc"\n'), "retire_old_role")
        self.assertEqual(c("mv -f ul.new pgbouncer/userlist.txt", '"mastodon" "md5cccc"\n'), "change_old_password")
        self.assertIsNone(c("cp /tmp/ul pgbouncer/userlist.txt", UL + '"mastodon_v2" "md5cc"\n'))
        self.assertEqual(c("cat /tmp/x > pgbouncer/userlist.txt", None), "change_old_password")  # unreadable source
        self.assertIsNone(c("cp pgbouncer/userlist.txt pgbouncer/userlist.txt.bak", UL))

    def test_other_files_not_covered(self):
        self.assertIsNone(fed("write_file", path=".env.production", content="DB_USER=mastodon_v2\n"))


class ConfigAndPrivate(unittest.TestCase):
    def test_bob_config_edit(self):
        self.assertEqual(kind(fed("write_file", path=".bob/mcp.json", content="{}")), "protect_config")
        self.assertEqual(kind(fed("apply_diff", path="/Users/x/mastodon-ops/.bob/settings.json", diff="x")), "protect_config")
        self.assertEqual(kind(cmd("sed -i '' 's/300/300000/' .bob/mcp.json")), "protect_config")
        self.assertIsNone(fed("read_file", path=".bob/mcp.json"))

    def test_private_read(self):
        c = fed("read_file", path="/home/u/.keyturn/answer-key.json")
        self.assertEqual(kind(c), "private")
        self.assertFalse(gate.decide(c, {})[0])


class FreeTextNeverCovered(unittest.TestCase):
    def test_texts(self):
        self.assertIsNone(fed("write_file", path="keyturn/plan.md", content="7. ALTER ROLE mastodon NOLOGIN; DROP ROLE mastodon"))
        self.assertIsNone(fed("attempt_completion", result="Run ALTER ROLE mastodon PASSWORD 'x'; next"))
        self.assertIsNone(fed("ask_followup_question", question="Shall I DROP ROLE mastodon now?"))
        self.assertIsNone(fed("write_file", path="keyturn/inventory.json", content="gaps: /home/u/.keyturn not inspected"))


class Decide(unittest.TestCase):
    def test_blocks_with_blockers_and_both_methods(self):
        c = cmd("psql -c 'ALTER ROLE mastodon PASSWORD \\'x\\''")
        allow, msg = gate.decide(c, {"change_old_password": {"ok": False, "blockers": ["pgbouncer.ini does not yet connect as mastodon with the new password"]}})
        self.assertFalse(allow)
        self.assertIn("pgbouncer.ini does not yet", msg)
        self.assertIn("SAME USER", msg)
        self.assertIn("NEW USER", msg)

    def test_allow_mentions_window(self):
        c = cmd("psql -c \"ALTER ROLE mastodon PASSWORD 'x'\"")
        allow, msg = gate.decide(c, {"change_old_password": {"ok": True, "blockers": []}})
        self.assertTrue(allow)
        self.assertIn("window", msg)

    def test_activation_block(self):
        c = cmd("docker compose up -d --force-recreate web")
        allow, msg = gate.decide(c, {"activate": {"ok": False, "blockers": ["Postgres refuses the user/password in .env.production"]}})
        self.assertFalse(allow)
        self.assertIn("Postgres does not accept", msg)

    def test_refusal_texts_never_name_the_hashed_copy(self):
        for c in (cmd("psql -c \"ALTER ROLE mastodon PASSWORD 'x'\""), cmd("psql -c 'ALTER ROLE mastodon NOLOGIN'"), cmd("docker restart web")):
            self.assertNotIn("userlist", gate.decide(c, {c["kind"]: {"ok": False, "blockers": ["b"]}})[1])

    def test_missing_readiness_fails_closed(self):
        self.assertFalse(gate.decide(cmd("psql -c 'ALTER ROLE mastodon NOLOGIN'"), {})[0])

    def test_unrelated_allowed(self):
        self.assertEqual(gate.decide(None, {}), (True, ""))


if __name__ == "__main__":
    unittest.main()
