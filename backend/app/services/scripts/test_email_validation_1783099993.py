def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    email_columns = config.get('columns', [])
    email_providers = config.get('providers', ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com'])
    email_pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'

    def validate_email(email):
        if pd.isnull(email):
            return False
        if not pd.is_string(email):
            return False
        if not re.match(email_pattern, email):
            return False
        domain = email.split('@')[-1]
        if domain not in email_providers:
            return False
        return True

    for column in email_columns:
        if column in df.columns:
            df[f'{column}_is_valid'] = df[column].apply(validate_email)
        else:
            raise ValueError(f'Column {column} not found in DataFrame')
    return df