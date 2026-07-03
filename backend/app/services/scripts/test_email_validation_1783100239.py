def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    email_columns = config.get('columns', [])
    email_providers = config.get('providers', ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com'])
    valid_emails = []

    def validate_email(email):
        if not email:
            return False
        if '@' not in email:
            return False
        local_part, domain = email.split('@')
        if '.' not in domain:
            return False
        if domain not in email_providers:
            return False
        return True

    for column in email_columns:
        if column in df.columns:
            df[f'{column}_is_valid'] = df[column].apply(validate_email)
        else:
            print(f"Warning: Column '{column}' not found in DataFrame.")
    
    return df