import unittest

from sync import CoursePage, assignment_type, build_properties, match_course, next_link


class SyncTests(unittest.TestCase):
    def test_matches_emory_course_codes_with_inserted_campus_marker(self):
        courses = [CoursePage("p1", "PHYS 125"), CoursePage("p2", "ECON 201")]
        matched = match_course({"course_code": "PHYS_OX 125-1"}, courses)
        self.assertEqual(matched, CoursePage("p1", "PHYS 125"))

    def test_unmatched_course_returns_none(self):
        courses = [CoursePage("p1", "PHYS 125")]
        self.assertIsNone(match_course({"course_code": "CHEM 150"}, courses))

    def test_assignment_type(self):
        self.assertEqual(assignment_type({"name": "Midterm 1"}), "💭 Exam")
        self.assertEqual(assignment_type({"name": "Week 3 Reading"}), "📖 Reading")
        self.assertEqual(assignment_type({"name": "Problem Set 2"}), "📝 Homework")

    def test_update_does_not_uncheck_manually_completed_assignment(self):
        properties = build_properties(
            {"id": 10},
            {
                "id": 20,
                "name": "Problem Set",
                "html_url": "https://canvas.example/assignment/20",
                "due_at": "2026-09-22T03:59:00Z",
                "updated_at": "2026-09-20T01:00:00Z",
                "submission": {"workflow_state": "unsubmitted"},
            },
            CoursePage("page-1", "ECON 201"),
            creating=False,
        )
        self.assertNotIn("Done", properties)

    def test_canvas_pagination_next_link(self):
        header = '<https://canvas.example/api?page=2>; rel="next", <https://canvas.example/api?page=4>; rel="last"'
        self.assertEqual(next_link(header), "https://canvas.example/api?page=2")


if __name__ == "__main__":
    unittest.main()
