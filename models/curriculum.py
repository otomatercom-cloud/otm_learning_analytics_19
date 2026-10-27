from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

REVISION_FREQUENCY = [
    ('1', '1 Day'),
    ('3', '3 Days'),
    ('7', '7 Days'),
    ('15', '15 Days'),
    ('30', '30 Days'),
]

DIFFICULTY = [
    ('easy', 'Easy'),
    ('medium', 'Medium'),
    ('hard', 'Hard'),
]


class OtmLearningSubject(models.Model):
    _name = 'otm.learning.subject'
    _description = 'Learning Analytics - Subject'
    _order = 'course_id, sequence, name'

    name = fields.Char(string='Subject', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(default=10)
    course_id = fields.Many2one('course.master', string='Course', required=True, ondelete='cascade')
    chapter_ids = fields.One2many('otm.learning.chapter', 'subject_id', string='Chapters')
    chapter_count = fields.Integer(compute='_compute_chapter_count')
    active = fields.Boolean(default=True)

    _name_course_uniq = models.Constraint(
        'unique(name, course_id)', 'This subject already exists for this course.')

    def _compute_chapter_count(self):
        data = self.env['otm.learning.chapter']._read_group(
            [('subject_id', 'in', self.ids)], ['subject_id'], ['__count'])
        mapped = {subject.id: count for subject, count in data}
        for rec in self:
            rec.chapter_count = mapped.get(rec.id, 0)


class OtmLearningChapter(models.Model):
    _name = 'otm.learning.chapter'
    _description = 'Learning Analytics - Chapter'
    _order = 'subject_id, sequence, name'

    name = fields.Char(string='Chapter', required=True)
    sequence = fields.Integer(default=10)
    subject_id = fields.Many2one('otm.learning.subject', string='Subject', required=True, ondelete='cascade')
    course_id = fields.Many2one(related='subject_id.course_id', store=True, string='Course')
    topic_ids = fields.One2many('otm.learning.topic', 'chapter_id', string='Topics')
    topic_count = fields.Integer(compute='_compute_topic_count')
    active = fields.Boolean(default=True)

    def _compute_topic_count(self):
        data = self.env['otm.learning.topic']._read_group(
            [('chapter_id', 'in', self.ids)], ['chapter_id'], ['__count'])
        mapped = {chapter.id: count for chapter, count in data}
        for rec in self:
            rec.topic_count = mapped.get(rec.id, 0)


class OtmLearningTopic(models.Model):
    _name = 'otm.learning.topic'
    _description = 'Learning Analytics - Topic'
    _order = 'chapter_id, sequence, name'

    name = fields.Char(string='Topic', required=True)
    sequence = fields.Integer(default=10)
    chapter_id = fields.Many2one('otm.learning.chapter', string='Chapter', required=True, ondelete='cascade')
    subject_id = fields.Many2one(related='chapter_id.subject_id', store=True, string='Subject')
    course_id = fields.Many2one(related='chapter_id.course_id', store=True, string='Course')

    difficulty = fields.Selection(DIFFICULTY, string='Difficulty', default='medium', required=True)
    priority = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
                                 string='Priority', default='medium', required=True)
    weightage = fields.Float(string='Exam Weightage (%)', default=0.0,
                              help='Approximate share of exam marks this topic carries, used to prioritise study plans.')
    estimated_study_time = fields.Float(string='Estimated Study Time (hrs)', default=1.0)
    revision_frequency = fields.Selection(REVISION_FREQUENCY, string='Revision Frequency',
                                           default='7', required=True,
                                           help='Spaced-repetition interval used to compute the next revision date.')
    active = fields.Boolean(default=True)

    @api.constrains('weightage')
    def _check_weightage(self):
        for rec in self:
            if not 0 <= rec.weightage <= 100:
                raise ValidationError(_('Exam weightage must be between 0 and 100.'))
