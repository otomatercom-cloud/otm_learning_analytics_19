from odoo import _, api, fields, models


class OtmStudentMentor(models.Model):
    _name = 'otm.student.mentor'
    _description = 'Learning Analytics - Mentor'
    _order = 'name'

    name = fields.Char(string='Mentor Name', required=True)
    user_id = fields.Many2one('res.users', string='User Account')
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    student_ids = fields.One2many('student.details', 'mentor_id', string='Assigned Students')
    student_count = fields.Integer(compute='_compute_student_count')
    active = fields.Boolean(default=True)

    _user_uniq = models.Constraint('unique(user_id)', 'This user is already a mentor.')

    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)


class StudentDetailsMentor(models.Model):
    _inherit = 'student.details'

    mentor_id = fields.Many2one('otm.student.mentor', string='Mentor')
    daily_study_hours = fields.Float(string='Daily Study Hours Budget', default=2.0)
    risk_level = fields.Selection(
        [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        string='Risk Level', compute='_compute_risk_level', store=True)

    @api.depends('learning_score')
    def _compute_risk_level(self):
        for student in self:
            score = student.learning_score or 0.0
            if score < 40:
                student.risk_level = 'high'
            elif score < 60:
                student.risk_level = 'medium'
            else:
                student.risk_level = 'low'
