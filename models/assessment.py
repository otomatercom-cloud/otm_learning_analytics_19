from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

QUESTION_TYPES = [
    ('mcq_single', 'MCQ (Single Correct)'),
    ('true_false', 'True / False'),
]

ATTEMPT_STATES = [
    ('in_progress', 'In Progress'),
    ('submitted', 'Submitted'),
    ('graded', 'Graded'),
]


class OtmLearningQuestion(models.Model):
    _name = 'otm.learning.question'
    _description = 'Learning Analytics - Question Bank'
    _order = 'topic_id, id'

    name = fields.Text(string='Question', required=True)
    question_type = fields.Selection(QUESTION_TYPES, string='Type', default='mcq_single', required=True)
    topic_id = fields.Many2one('otm.learning.topic', string='Topic', required=True, ondelete='cascade')
    chapter_id = fields.Many2one(related='topic_id.chapter_id', store=True, string='Chapter')
    subject_id = fields.Many2one(related='topic_id.subject_id', store=True, string='Subject')
    difficulty = fields.Selection([('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')],
                                  string='Difficulty', default='medium', required=True)
    marks = fields.Float(string='Default Marks', default=1.0, required=True)
    option_ids = fields.One2many('otm.learning.question.option', 'question_id', string='Options')
    active = fields.Boolean(default=True)

    @api.constrains('option_ids', 'question_type')
    def _check_options(self):
        for rec in self:
            if not rec.option_ids:
                continue
            correct = rec.option_ids.filtered('is_correct')
            if rec.question_type in ('mcq_single', 'true_false') and len(correct) != 1:
                raise ValidationError(_(
                    "'%s' must have exactly one correct option.") % (rec.name or '')[:60])

    def action_set_true_false_options(self):
        """Convenience: wipes and re-creates the standard True/False pair."""
        for rec in self:
            rec.option_ids.unlink()
            rec.option_ids = [
                (0, 0, {'name': _('True'), 'is_correct': False, 'sequence': 1}),
                (0, 0, {'name': _('False'), 'is_correct': False, 'sequence': 2}),
            ]


class OtmLearningQuestionOption(models.Model):
    _name = 'otm.learning.question.option'
    _description = 'Learning Analytics - Question Option'
    _order = 'question_id, sequence, id'

    question_id = fields.Many2one('otm.learning.question', required=True, ondelete='cascade')
    name = fields.Char(string='Option Text', required=True)
    is_correct = fields.Boolean(string='Correct')
    sequence = fields.Integer(default=10)


class OtmLearningQuiz(models.Model):
    _name = 'otm.learning.quiz'
    _description = 'Learning Analytics - Quiz'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Quiz Title', required=True, tracking=True)
    topic_id = fields.Many2one('otm.learning.topic', string='Topic', required=True, tracking=True)
    chapter_id = fields.Many2one(related='topic_id.chapter_id', store=True, string='Chapter')
    subject_id = fields.Many2one(related='topic_id.subject_id', store=True, string='Subject')
    batch_id = fields.Many2one('student.batch', string='Batch', required=True, tracking=True)
    duration_minutes = fields.Integer(string='Duration (minutes)', default=15)
    pass_percentage = fields.Float(string='Pass %', default=40.0)

    question_ids = fields.Many2many('otm.learning.question', string='Questions')
    question_count = fields.Integer(compute='_compute_totals', store=True)
    total_marks = fields.Float(compute='_compute_totals', store=True)

    # Gate: controlled by the mentor-approval workflow (Phase 2b); defaults locked
    # so a quiz is never attemptable just because it exists.
    is_locked = fields.Boolean(string='Locked', default=True, tracking=True,
                                help='While locked, students cannot start an attempt. '
                                     'Unlocked automatically when a mentor approves the '
                                     'linked study plan (Phase 2b), or manually here.')
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('closed', 'Closed')],
                             default='draft', required=True, tracking=True)

    attempt_ids = fields.One2many('otm.learning.quiz.attempt', 'quiz_id', string='Attempts')
    attempt_count = fields.Integer(compute='_compute_attempt_count')

    @api.depends('question_ids', 'question_ids.marks')
    def _compute_totals(self):
        for rec in self:
            rec.question_count = len(rec.question_ids)
            rec.total_marks = sum(rec.question_ids.mapped('marks'))

    def _compute_attempt_count(self):
        data = self.env['otm.learning.quiz.attempt']._read_group(
            [('quiz_id', 'in', self.ids)], ['quiz_id'], ['__count'])
        mapped = {quiz.id: count for quiz, count in data}
        for rec in self:
            rec.attempt_count = mapped.get(rec.id, 0)

    def action_activate(self):
        for rec in self:
            if not rec.question_ids:
                raise UserError(_("Add at least one question before activating the quiz."))
            rec.state = 'active'

    def action_lock(self):
        self.write({'is_locked': True})

    def action_unlock(self):
        self.write({'is_locked': False})

    def action_view_attempts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Attempts - %s', self.name),
            'res_model': 'otm.learning.quiz.attempt', 'view_mode': 'list,form',
            'domain': [('quiz_id', '=', self.id)],
        }

    def start_attempt(self, student):
        """Server-side entry point (also used by the future API layer).
        Real enforcement of the mentor gate lives here, not just in the UI."""
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_("This quiz is not active."))
        if self.is_locked:
            raise UserError(_("This quiz is locked until your mentor approves your study plan."))
        existing = self.attempt_ids.filtered(
            lambda a: a.student_id == student and a.state != 'graded')
        if existing:
            return existing[0]
        return self.env['otm.learning.quiz.attempt'].create({
            'quiz_id': self.id,
            'student_id': student.id,
        })


class OtmLearningQuizAttempt(models.Model):
    _name = 'otm.learning.quiz.attempt'
    _description = 'Learning Analytics - Quiz Attempt'
    _order = 'id desc'

    quiz_id = fields.Many2one('otm.learning.quiz', required=True, ondelete='cascade')
    student_id = fields.Many2one('student.details', required=True, ondelete='cascade')
    start_datetime = fields.Datetime(default=fields.Datetime.now, required=True)
    end_datetime = fields.Datetime()
    state = fields.Selection(ATTEMPT_STATES, default='in_progress', required=True)
    answer_ids = fields.One2many('otm.learning.quiz.attempt.answer', 'attempt_id', string='Answers')

    marks_obtained = fields.Float(compute='_compute_result', store=True)
    percentage = fields.Float(compute='_compute_result', store=True)
    passed = fields.Boolean(compute='_compute_result', store=True)

    @api.depends('answer_ids.marks_obtained', 'answer_ids.question_id.marks', 'quiz_id.total_marks',
                 'quiz_id.pass_percentage')
    def _compute_result(self):
        for rec in self:
            total = rec.quiz_id.total_marks or 0.0
            obtained = sum(rec.answer_ids.mapped('marks_obtained'))
            rec.marks_obtained = obtained
            rec.percentage = (obtained / total * 100.0) if total else 0.0
            rec.passed = rec.percentage >= (rec.quiz_id.pass_percentage or 0.0)

    def action_submit(self):
        for rec in self:
            if rec.state != 'in_progress':
                continue
            rec.answer_ids._auto_grade()
            rec.write({'state': 'graded', 'end_datetime': fields.Datetime.now()})
        return True


class OtmLearningQuizAttemptAnswer(models.Model):
    _name = 'otm.learning.quiz.attempt.answer'
    _description = 'Learning Analytics - Quiz Attempt Answer'
    _order = 'attempt_id, id'

    attempt_id = fields.Many2one('otm.learning.quiz.attempt', required=True, ondelete='cascade')
    question_id = fields.Many2one('otm.learning.question', required=True, ondelete='cascade')
    selected_option_id = fields.Many2one('otm.learning.question.option', string='Selected Option')
    is_correct = fields.Boolean(readonly=True)
    marks_obtained = fields.Float(readonly=True)

    _attempt_question_uniq = models.Constraint(
        'unique(attempt_id, question_id)', 'This question has already been answered in this attempt.')

    def _auto_grade(self):
        for ans in self:
            correct_option = ans.question_id.option_ids.filtered('is_correct')[:1]
            is_correct = bool(ans.selected_option_id) and ans.selected_option_id == correct_option
            ans.write({
                'is_correct': is_correct,
                'marks_obtained': ans.question_id.marks if is_correct else 0.0,
            })
