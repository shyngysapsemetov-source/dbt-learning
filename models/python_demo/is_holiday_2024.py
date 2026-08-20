import holidays
import pandas

# All python models need to be defined at the start with this specific syntax
def model(dbt, session):

# Python model don't use Jinja. Here we are using dbt.config to create model configurations
# Be sure to materialize python models as tables, and to specify the packages that were imported above
    dbt.config(
        materialized="table",
        packages=['pandas', 'pyarrow', 'holidays']
    )

    us_holidays = holidays.US()

# Python models don't use Jinja. Here we are using dbt.ref to create a model references
    df = dbt.ref('date_spine').to_pandas()

# Applying lambda function to create a new column is_holiday
    df['IS_HOLIDAY'] = df['DATE_DAY'].apply(lambda date: date in us_holidays)

# In dbt, you alwyas need to return your data frame at the end of your model
    return df