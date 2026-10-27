from datetime import timedelta

from odoo import _, api, fields, models

STATUS = [
    ('not_started', 'Not Started'),
    ('learning', 'Learning'),
    ('completed', 'Completed'),
    ('revision_needed', 'Revision Needed'),
    ('weak', 'Weak'),
    ('mastered', 'Mastered'),
]

CONFIDENCE = [('1', '1 - Very Low'), ('2', '2 - Low'), ('3', '3 - Medium'),
              ('4', '4 - High'), ('5', '5 - Very High')]


class OtmStudentTopicProgress(models.Model):
    _name = 'otm.student.topic.progress'
    _description = 'Student Topic Progress'
    _order = 'student_id, topic_id'

    student_id = fields.Many2one('student.details', string='Student', required=True,
                                  ondelete='cascade', index=True)
    topic_id = fields.Many2one('otm.learning.topic', string='Topic', required=True,
                                ondelete='cascade', index=True)
    chapter_id = fields.Many2one(related='topic_id.chapter_id', store=True, string='Chapter')
    subject_id = fields.Many2one(related='topic_id.subject_id', store=True, string='Subject')

    completion_percentage = fields.Float(string='Completion %', default=0.0)
    status = fields.Selection(STATUS, string='Status', default='not_started', required=True)
    confidence_level = fields.Selection(CONFIDENCE, string='Confidence', default='3')
    student_self_rating = fields.Integer(string='Student Self Rating (1-5)')
    faculty_rating = fields.Integer(string='Faculty Rating (1-5)')
    practice_accuracy = fields.Float(string='Practice Accuracy %', default=0.0)

    last_activity_date = fields.Date(string='Last Studied On', default=fields.Date.context_today)
    next_revision_date = fields.Date(string='Next Revision Due', compute='_compute_revision',
                                      store=True)
    is_revision_due = fields.Boolean(string='Revision Due', compute='_compute_revision', store=True)

    weakness_score = fields.Float(string='Weakness Score', compute='_compute_weakness', store=True,
                                   help='0 (strong) to 100 (very weak) - derived from status, '
                                        'accuracy, overdue revision and confidence.')
    is_weak_area = fields.Boolean(string='Weak Area', compute='_compute_weakness', store=True)

    _student_topic_uniq = models.Constraint(
        'unique(student_id, topic_id)', 'Progress for this student/topic already exists.')

    @api.depends('last_activity_date', 'topic_id.revision_frequency', 'status')
    def _compute_revision(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.last_activity_date or rec.status in ('not_started',):
                rec.next_revision_date = False
                rec.is_revision_due = False
                continue
            days = int(rec.topic_id.revision_frequency or '7')
            rec.next_revision_date = rec.last_activity_date + timedelta(days=days)
            rec.is_revision_due = rec.next_revision_date <= today

    @api.depends('status', 'practice_accuracy', 'is_revision_due', 'confidence_level')
    def _compute_weakness(self):
        for rec in self:
            score = 0.0
            if rec.status == 'weak':
                score += 40
            elif rec.status == 'revision_needed':
                score += 20
            elif rec.status == 'not_started':
                score += 10
            if rec.practice_accuracy and rec.practice_accuracy < 50:
                score += 25
            elif rec.practice_accuracy and rec.practice_accuracy < 70:
                score += 10
            if rec.is_revision_due:
                score += 15
            if rec.confidence_level in ('1', '2'):
                score += 15
            rec.weakness_score = min(score, 100.0)
            rec.is_weak_area = rec.weakness_score >= 40

    def action_mark_studied_today(self):
        for rec in self:
            rec.last_activity_date = fields.Date.context_today(rec)
            if rec.status == 'not_started':
                rec.status = 'learning'
