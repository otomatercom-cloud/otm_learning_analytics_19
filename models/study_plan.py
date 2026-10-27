from odoo import _, api, fields, models
from odoo.exceptions import UserError

PLAN_STATES = [
    ('draft', 'Draft'),
    ('assigned', 'Assigned'),
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('reviewed', 'Reviewed'),
    ('approved', 'Approved'),
    ('revision_required', 'Revision Required'),
    ('assessment_open', 'Assessment Open'),
    ('finished', 'Finished'),
]


class OtmStudentStudyPlan(models.Model):
    _name = 'otm.student.study.plan'
    _description = 'Learning Analytics - Student Study Plan'
    _inherit = ['mail.thread']
    _order = 'plan_date desc, id desc'

    student_id = fields.Many2one('student.details', required=True, ondelete='cascade', tracking=True)
    plan_date = fields.Date(string='Plan Date', default=fields.Date.context_today, required=True)
    is_revision_plan = fields.Boolean(string='Revision Plan', default=False)
    state = fields.Selection(PLAN_STATES, default='draft', required=True, tracking=True)

    task_ids = fields.One2many('otm.student.study.task', 'plan_id', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_count')
    total_hours = fields.Float(compute='_compute_task_count')

    # Mentor review
    mentor_remarks = fields.Text(string='Mentor Remarks')
    mentor_rating = fields.Integer(string='Mentor Rating (1-5)')
    reviewed_by = fields.Many2one('res.users', string='Reviewed By', readonly=True)
    reviewed_date = fields.Datetime(string='Reviewed On', readonly=True)

    # Assessment gate — the real mentor-approval enforcement point
    assessment_quiz_id = fields.Many2one(
        'otm.learning.quiz', string='Linked Assessment',
        domain="[('topic_id', 'in', task_ids.topic_id)]",
        help='The quiz that gates on this plan being approved. Left blank until a '
             'manager/mentor picks one at review time.')

    _student_date_revision_uniq = models.Constraint(
        'unique(student_id, plan_date, is_revision_plan)',
        'A plan for this student on this date already exists.')

    def _compute_task_count(self):
        for rec in self:
            rec.task_count = len(rec.task_ids)
            rec.total_hours = sum(rec.task_ids.mapped('duration_hours'))

    # ------------------------------------------------------------- generator
    @api.model
    def _score_topics(self, student):
        """Priority-scores every non-mastered tracked topic for this student:
        weighs completion gap, weakness, exam weightage/priority, revision-due
        and difficulty. Returns a list of (score, progress_record) sorted
        highest priority first."""
        progress = self.env['otm.student.topic.progress'].search([('student_id', '=', student.id)])
        scored = []
        for p in progress:
            if p.status == 'mastered':
                continue
            completion_gap = 100.0 - (p.completion_percentage or 0.0)
            priority_weight = {'low': 0.3, 'medium': 0.6, 'high': 1.0}.get(p.topic_id.priority, 0.6)
            difficulty_weight = {'easy': 0.3, 'medium': 0.6, 'hard': 1.0}.get(p.topic_id.difficulty, 0.6)
            score = (
                completion_gap * 0.30
                + (p.weakness_score or 0.0) * 0.30
                + (p.topic_id.weightage or 0.0) * 0.20
                + (20.0 if p.is_revision_due else 0.0)
                + priority_weight * 10.0
                + difficulty_weight * 5.0
            )
            scored.append((score, p))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored

    def _build_tasks(self):
        """Fills THIS plan's task_ids from a fresh priority scoring. Assumes
        task_ids is already empty (caller's responsibility) — idempotent to
        call again after an unlink()."""
        self.ensure_one()
        budget = self.student_id.daily_study_hours or 2.0
        used = 0.0
        sequence = 1
        for score, p in self._score_topics(self.student_id):
            if used >= budget:
                break
            duration = min(p.topic_id.estimated_study_time or 1.0, budget - used)
            if duration <= 0:
                continue
            self.env['otm.student.study.task'].create({
                'plan_id': self.id,
                'topic_id': p.topic_id.id,
                'activity': _('Revise') if p.is_revision_due else _('Study'),
                'duration_hours': duration,
                'priority_score': score,
                'sequence': sequence,
            })
            used += duration
            sequence += 1

    @api.model
    def generate_for_student(self, student, plan_date=None, is_revision=False):
        """Entry point used by the cron / Request Revision / first-time
        generation. Idempotent per (student, date, is_revision) via the
        unique constraint — returns the existing plan untouched if one
        already exists, rather than duplicating it."""
        plan_date = plan_date or fields.Date.context_today(self)
        existing = self.search([
            ('student_id', '=', student.id), ('plan_date', '=', plan_date),
            ('is_revision_plan', '=', is_revision),
        ], limit=1)
        if existing:
            return existing
        plan = self.create({
            'student_id': student.id, 'plan_date': plan_date,
            'is_revision_plan': is_revision, 'state': 'assigned',
        })
        plan._build_tasks()
        return plan

    def action_generate_tasks(self):
        """Manual re-generation button on an existing plan — clears its
        tasks and rebuilds them from a fresh scoring, in place."""
        for rec in self:
            rec.task_ids.unlink()
            rec._build_tasks()

    # ------------------------------------------------------------- workflow
    def action_submit_for_review(self):
        self.write({'state': 'completed'})

    def action_mark_reviewed(self):
        self.write({
            'state': 'reviewed',
            'reviewed_by': self.env.user.id,
            'reviewed_date': fields.Datetime.now(),
        })

    def action_approve(self):
        for rec in self:
            if rec.state != 'reviewed':
                raise UserError(_("Mark the plan reviewed before approving it."))
            rec.write({'state': 'approved'})

    def action_request_revision(self):
        for rec in self:
            rec.write({'state': 'revision_required'})
            self.generate_for_student(rec.student_id, fields.Date.context_today(rec), is_revision=True)

    def action_open_assessment(self):
        """The real enforcement step: unlocking the quiz IS the gate -
        this is not advisory, the quiz's own start_attempt() checks is_locked."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Approve the plan before opening its assessment."))
            if not rec.assessment_quiz_id:
                raise UserError(_("Pick an assessment quiz on this plan first."))
            rec.assessment_quiz_id.action_unlock()
            rec.write({'state': 'assessment_open'})

    def action_mark_finished(self):
        self.write({'state': 'finished'})

    # ------------------------------------------------------- attempt feedback
    def _handle_quiz_result(self, attempt):
        """Called from otm.learning.quiz.attempt.action_submit(). Finds the plan
        this attempt's quiz was opened for and finalises it: pass -> finished
        (quiz re-locked so it can't be retaken silently); fail -> revision
        plan auto-generated and the quiz re-locked until the mentor re-approves."""
        plans = self.search([
            ('assessment_quiz_id', '=', attempt.quiz_id.id),
            ('student_id', '=', attempt.student_id.id),
            ('state', '=', 'assessment_open'),
        ])
        for plan in plans:
            attempt.quiz_id.action_lock()
            if attempt.passed:
                plan.action_mark_finished()
            else:
                plan.action_request_revision()


class OtmStudentStudyTask(models.Model):
    _name = 'otm.student.study.task'
    _description = 'Learning Analytics - Study Task'
    _order = 'plan_id, sequence, id'

    plan_id = fields.Many2one('otm.student.study.plan', required=True, ondelete='cascade')
    topic_id = fields.Many2one('otm.learning.topic', required=True)
    activity = fields.Char(string='Activity', required=True)
    duration_hours = fields.Float(string='Duration (hrs)', required=True)
    priority_score = fields.Float(string='Priority Score', readonly=True)
    sequence = fields.Integer(default=10)
    done = fields.Boolean(string='Done')
    time_spent = fields.Float(string='Time Spent (hrs)')
