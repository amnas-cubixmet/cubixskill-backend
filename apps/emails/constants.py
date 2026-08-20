class EmailTemplateCodes:
    ACADEMY_ACCOUNT_SETUP = 'ACADEMY_ACCOUNT_SETUP'
    PASSWORD_RESET = 'PASSWORD_RESET'
    PASSWORD_CHANGED = 'PASSWORD_CHANGED'
    EMAIL_VERIFICATION = 'EMAIL_VERIFICATION'
    STUDENT_ACTIVATION = 'STUDENT_ACTIVATION'

SUBJECTS = {
    EmailTemplateCodes.ACADEMY_ACCOUNT_SETUP: "Activate Your CubixSkill Academy Account",
    EmailTemplateCodes.PASSWORD_RESET: "Reset Your CubixSkill Password",
    EmailTemplateCodes.PASSWORD_CHANGED: "Security Alert: Your CubixSkill Password Was Changed",
    EmailTemplateCodes.EMAIL_VERIFICATION: "Verify Your CubixSkill Email Address",
    EmailTemplateCodes.STUDENT_ACTIVATION: "Activate Your Student Account – {academy_name}",
}
