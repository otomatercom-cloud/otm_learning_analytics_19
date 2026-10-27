from odoo import _, api, fields, models

# Learning Score weights (sum to 100)
W_COMPLETION = 20
W_ATTENDANCE = 20
W_PRACTICE = 15
W_TEST_MARKS = 25
W_REVISION = 10
W_CONSISTENCY = 10


class StudentDetailsLearningAnalytics(models.Model):
    _inherit = 'student.details'

    topic_progress_ids = fields.One2many('otm.student.topic.progress', 'student_id',
                                          string='Topic Progress')
    exam_line_ids = fields.One2many('otm.exam.line', 'student_id', string='Exam Marks (Analytics)')

    weak_topic_count = fields.Integer(string='Weak Topics', compute='_compute_learning_score')
    mastered_topic_count = fields.Integer(string='Mastered Topics', compute='_compute_learning_score')

    score_completion = fields.Float(string='Completion Score', compute='_compute_learning_score', store=True)
    score_attendance = fields.Float(string='Attendance Score', compute='_compute_learning_score', store=True)
    score_practice = fields.Float(string='Practice Score', compute='_compute_learning_score', store=True)
    score_test_marks = fields.Float(string='Test Marks Score', compute='_compute_learning_score', store=True)
    score_revision = fields.Float(string='Revision Score', compute='_compute_learning_score', store=True)
    score_consistency = fields.Float(
        string='Consistency Score', compute='_compute_learning_score', store=True,
        help='Not yet computed in this phase - requires the daily Study Plan task log '
             '(Phase 2). Counted as 0 for now; Learning Score below is therefore a partial '
             'score out of 90, not a faked 100.')
    learning_score = fields.Float(string='Learning Score', compute='_compute_learning_score',
                                   store=True, digits=(5, 1))

    @api.depends('topic_progress_ids.completion_percentage', 'topic_progress_ids.practice_accuracy',
                 'topic_progress_ids.is_revision_due', 'topic_progress_ids.status',
                 'topic_progress_ids.next_revision_date',
                 'exam_line_ids.percentage', 'exam_line_ids.status', 'exam_line_ids.exam_state',
                 'overall_attendance')
    def _compute_learning_score(self):
        for student in self:
            progress = student.topic_progress_ids
            student.weak_topic_count = len(progress.filtered('is_weak_area'))
            student.mastered_topic_count = len(progress.filtered(lambda p: p.status == 'mastered'))

            # Completion: average completion % across all tracked topics
            student.score_completion = (
                (sum(progress.mapped('completion_percentage')) / len(progress)) if progress else 0.0
            ) / 100.0 * W_COMPLETION

            # Attendance: reuses student_details_19's own overall_attendance (%)
            student.score_attendance = (student.overall_attendance or 0.0) / 100.0 * W_ATTENDANCE

            # Practice: average practice accuracy across topics that have any practice recorded
            practiced = progress.filtered(lambda p: p.practice_accuracy)
            student.score_practice = (
                (sum(practiced.mapped('practice_accuracy')) / len(practiced)) if practiced else 0.0
            ) / 100.0 * W_PRACTICE

            # Test Marks: average % across published, appeared exam lines (otm.exam.line)
            appeared = student.exam_line_ids.filtered(
                lambda l: l.exam_state == 'published' and l.status == 'appeared')
            student.score_test_marks = (
                (sum(appeared.mapped('percentage')) / len(appeared)) if appeared else 0.0
            ) / 100.0 * W_TEST_MARKS

            # Revision: share of topics (with a revision date set) that are NOT overdue
            due_tracked = progress.filtered('next_revision_date')
            on_time = due_tracked.filtered(lambda p: not p.is_revision_due)
            student.score_revision = (
                (len(on_time) / len(due_tracked) * 100.0) if due_tracked else 0.0
            ) / 100.0 * W_REVISION

            # Consistency: deferred to Phase 2 (Study Plan daily completion log)
            student.score_consistency = 0.0

            student.learning_score = (
                student.score_completion + student.score_attendance + student.score_practice
                + student.score_test_marks + student.score_revision + student.score_consistency
            )

    def action_view_topic_progress(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Topic Progress - %s', self.name),
            'res_model': 'otm.student.topic.progress',
            'view_mode': 'list,kanban',
            'domain': [('student_id', '=', self.id)],
        }
