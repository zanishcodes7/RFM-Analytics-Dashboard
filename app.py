import os
from flask import Flask, render_template, send_file, request
import mysql.connector
from mysql.connector import Error
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
from scipy import stats

app = Flask(__name__)

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "port": int(os.environ.get("DB_PORT", 3306)),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

RFM_QUERY = """
    SELECT *,
    CONCAT(Recency_Score, Frequency_Score, Monetary_Score) AS RFM_CODE,
    CASE 
        WHEN Recency_Score >= 4 AND Frequency_Score >=4 AND Monetary_Score >= 4 THEN 'CHAMPIONS'
        WHEN Recency_Score <= 2 AND (Frequency_Score >=4 AND Monetary_Score >= 4) THEN 'At Risk'
        WHEN Recency_Score >= 4 AND Frequency_Score < 4 THEN 'New Customers'
        ELSE 'LOST'
    END AS SEGMENT
    FROM (
        SELECT CustomerID, MAX(InvoiceDate) AS last_order_date,
        COUNT(DISTINCT InvoiceNo) AS Frequency,
        SUM(Quantity*UnitPrice) AS Monetary,
        datediff('2025-01-01', MAX(InvoiceDate)) AS Recency_days,
        NTILE(5) OVER (ORDER BY COUNT(DISTINCT InvoiceNo)) AS Frequency_Score,
        NTILE(5) OVER (ORDER BY SUM(Quantity*UnitPrice)) AS Monetary_Score,
        NTILE(5) OVER (ORDER BY datediff('2025-01-01', MAX(InvoiceDate)) DESC) AS Recency_Score
        FROM online_retail_large
        GROUP BY CustomerID
    ) AS RFM_Table
    ORDER BY 
    CASE SEGMENT
        WHEN 'CHAMPIONS' THEN 1
        WHEN 'At Risk' THEN 2
        WHEN 'New Customers' THEN 3
        WHEN 'LOST' THEN 4
    END
"""

SEGMENT_COUNT_QUERY = """
    SELECT SEGMENT, COUNT(*) AS customer_count
    FROM (
        SELECT 
        CASE 
            WHEN Recency_Score >= 4 AND Frequency_Score >=4 AND Monetary_Score >= 4 THEN 'CHAMPIONS'
            WHEN Recency_Score <= 2 AND (Frequency_Score >=4 AND Monetary_Score >= 4) THEN 'At Risk'
            WHEN Recency_Score >= 4 AND Frequency_Score < 4 THEN 'New Customers'
            ELSE 'LOST'
        END AS SEGMENT
        FROM (
            SELECT CustomerID, 
                   COUNT(DISTINCT InvoiceNo) AS Frequency,
                   SUM(Quantity*UnitPrice) AS Monetary,
                   datediff('2025-01-01', MAX(InvoiceDate)) AS Recency_days,
                   NTILE(5) OVER (ORDER BY COUNT(DISTINCT InvoiceNo)) AS Frequency_Score,
                   NTILE(5) OVER (ORDER BY SUM(Quantity*UnitPrice)) AS Monetary_Score,
                   NTILE(5) OVER (ORDER BY datediff('2025-01-01', MAX(InvoiceDate)) DESC) AS Recency_Score
            FROM online_retail_large
            GROUP BY CustomerID
        ) AS scored
    ) AS labeled
    GROUP BY SEGMENT
"""


def get_stats_result(result):
    champion_spend = [float(row[3]) for row in result if row[9] == "CHAMPIONS"]
    lost_spend = [float(row[3]) for row in result if row[9] == "LOST"]
    t_stat, p_value = stats.ttest_ind(champion_spend, lost_spend)
    if p_value < 0.05:
        return f"Champions spend significantly more than Lost customers (p = {p_value:.4f})"
    else:
        return f"No statistically significant difference found in spending between Champions and Lost customers (p = {p_value:.4f})"


@app.route('/')
def home():
    connection = None
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()

        cursor.execute(RFM_QUERY)
        result = cursor.fetchall()

        cursor.execute(SEGMENT_COUNT_QUERY)
        segment_counts = cursor.fetchall()

        stats_result = get_stats_result(result)

        return render_template('index.html', customers=result, segment_counts=segment_counts,
                                stats_result=stats_result, searched_customer=None)
    except Error as e:
        return f"Something is wrong: {e}"
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


@app.route('/search')
def search():
    connection = None
    try:
        customer_id = request.args.get('customer_id')

        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()

        cursor.execute(RFM_QUERY)
        result = cursor.fetchall()

        cursor.execute(SEGMENT_COUNT_QUERY)
        segment_counts = cursor.fetchall()

        stats_result = get_stats_result(result)

        searched_customer = None
        if customer_id:
            for row in result:
                if str(row[0]) == customer_id.strip():
                    searched_customer = row
                    break

        return render_template('index.html', customers=result, segment_counts=segment_counts,
                                stats_result=stats_result, searched_customer=searched_customer,
                                searched_id=customer_id)
    except Error as e:
        return f"Something is wrong: {e}"
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


@app.route('/chart.png')
def chart():
    connection = None
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor()

        cursor.execute(SEGMENT_COUNT_QUERY)
        segment_counts = cursor.fetchall()

        labels = [row[0] for row in segment_counts]
        values = [row[1] for row in segment_counts]

        fig, ax = plt.subplots()
        ax.pie(values, labels=labels, autopct='%1.1f%%')

        img = io.BytesIO()
        fig.savefig(img, format='png')
        img.seek(0)
        return send_file(img, mimetype='image/png')
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()


if __name__ == "__main__":
    app.run(debug=True)