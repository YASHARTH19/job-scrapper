from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import time
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import traceback

# -----------------------------
# CONFIGURATION
# -----------------------------
load_dotenv()

LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD")
OUTPUT_FILE = "linkedin_jobs_detailed.xlsx"

# -----------------------------
# SELENIUM SETUP
# -----------------------------
def setup_driver(headless=True):
    chrome_options = Options()
    
    # Always headless in production/docker
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Simple strategy usually works best if 'normal' hangs
    chrome_options.page_load_strategy = 'eager' 

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver

# -----------------------------
# HELPERS
# -----------------------------
def extract_salary(text):
    if not text:
        return "N/A"
    patterns = [
        r'[\₹\$\€]\s?[\d,]+(?:\s?[kK]|\s?[lL]akhs?|\s?[cC]rores?|\s?[mM]ill?|)?', 
        r'\d+(?:\.\d+)?\s?LPA',
        r'CTC\s?:?\s?[\d,]+',
        r'Stipend\s?:?\s?[\d,]+'
    ]
    matches = []
    for p in patterns:
        found = re.findall(p, text, re.IGNORECASE)
        matches.extend(found)
    
    return ", ".join(list(set(matches))) if matches else "Not disclosed"

# -----------------------------
# LOGIN
# -----------------------------
def linkedin_login(driver):
    print("Navigating to LinkedIn login page...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    try:
        if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
            raise ValueError("Credentials missing in .env")

        driver.find_element(By.ID, "username").send_keys(LINKEDIN_EMAIL)
        driver.find_element(By.ID, "password").send_keys(LINKEDIN_PASSWORD)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        
        # Wait for either feed or checkpoint
        try:
             WebDriverWait(driver, 15).until(lambda d: "feed" in d.current_url or "checkpoint" in d.current_url or "challenge" in d.current_url)
        except:
             print("Timeout waiting for login redirect. Checking if we are still on login page...")
             if "login" in driver.current_url:
                 return False

        if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
            print("Security check triggered. PLEASE SOLVE IT MANUALLY IN THE BROWSER.")
            # Wait up to 3 minutes for user to solve
            WebDriverWait(driver, 180).until(lambda d: "feed" in d.current_url)
        
        print("Logged in successfully.")
        return True
    except Exception as e:
        print(f"Login failed: {e}")
        return False

# -----------------------------
# SCRAPE JOBS
# -----------------------------
def run_scraper(domains, limit=5):
    driver = setup_driver(headless=False)
    all_jobs = []
    debug_log = []
    
    try:
        if not linkedin_login(driver):
            return "Login Failed. Check credentials or CAPTCHA."
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"jobs_{timestamp}.xlsx"
        
        for domain in domains:
            print(f"\nScanning for domain: {domain}")
            # Ensure proper URL encoding
            formatted_domain = domain.replace(" ", "%20")
            url = f"https://www.linkedin.com/jobs/search/?keywords={formatted_domain}&location=India&f_TPR=r604800&origin=JOB_SEARCH_PAGE_JOB_FILTER"
            driver.get(url)
            
            # Explicit wait for any results
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "ul.jobs-search__results-list, .jobs-search-results-list, .job-card-container, .job-search-card"))
                )
            except:
                debug_log.append(f"{domain}: Timeout waiting for job list.")
                # Continue anyway, maybe static list
            
            # Scroll
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

            # Collect Links
            job_links = []
            try:
                # Try multiple selectors for job cards
                # Selector 1: Standard search results
                cards = driver.find_elements(By.CSS_SELECTOR, ".job-card-container")
                if not cards:
                     # Selector 2: Public job search cards
                     cards = driver.find_elements(By.CSS_SELECTOR, ".job-search-card")
                if not cards:
                     # Selector 3: List items
                     cards = driver.find_elements(By.CSS_SELECTOR, "li.jobs-search-results__list-item")
                
                print(f"Found {len(cards)} cards for {domain}")
                
                count = 0
                for card in cards:
                    if count >= limit: break
                    try:
                        anchor = card.find_element(By.TAG_NAME, "a")
                        href = anchor.get_attribute("href")
                        if href and "/jobs/view/" in href:
                             link = href.split("?")[0]
                             if link not in job_links:
                                 job_links.append(link)
                                 count += 1
                        elif href:
                             # Sometimes links are like /jobs/search/ -> ignore
                             # Or redirects. 
                             job_links.append(href)
                             count += 1
                    except:
                        continue
            except Exception as e:
                debug_log.append(f"{domain}: Error finding cards {str(e)}")

            if not job_links:
                debug_log.append(f"{domain}: No links found.")

            # Visit Links
            for link in job_links:
                try:
                    driver.get(link)
                    # Random sleep
                    time.sleep(2)
                    
                    # Extract Data with Wait
                    try:
                        WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
                    except: pass
                    
                    title = driver.title 
                    try:
                        title = driver.find_element(By.TAG_NAME, "h1").text
                    except: pass
                    
                    description = "N/A"
                    try:
                        description = driver.find_element(By.ID, "job-details").text
                    except:
                        try:
                             # Try older selectors
                             description = driver.find_element(By.CLASS_NAME, "description__text").text
                        except: pass

                    # If we still don't have description, try expanding "See more"
                    if description == "N/A":
                        try:
                            # Attempt to find button
                            btn = driver.find_element(By.CSS_SELECTOR, "[aria-label='Click to see more description']")
                            btn.click()
                            time.sleep(1)
                            description = driver.find_element(By.ID, "job-details").text
                        except: pass

                    salary = extract_salary(description)
                    
                    all_jobs.append({
                        "Title": title,
                        "Domain": domain,
                        "Apply Link": link,
                        "Salary/Stipend/CTC": salary,
                        "Description (Snippet)": description[:500]
                    })
                except Exception as e:
                    print(f"Error scraping {link}: {e}")
                    continue
        
        if all_jobs:
            df = pd.DataFrame(all_jobs)
            df.to_excel(filename, index=False)
            return filename
        else:
            return f"No jobs found. Debug: {'; '.join(debug_log)}"
            
    except Exception as e:
        traceback.print_exc()
        return f"Script Crash: {str(e)}"
    finally:
        driver.quit()

if __name__ == "__main__":
    # Debug mode
    print("Testing scraper...")
    res = run_scraper(["Data Science"], 2)
    print(res)
