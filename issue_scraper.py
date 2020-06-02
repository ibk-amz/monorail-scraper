import datetime
import time
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple, Collection, NewType, Iterator

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium import webdriver

import regex_util
from regex_util import capture


@dataclass
class Comment:
    index: int
    author: str
    author_roles: List[str]
    published: datetime.datetime
    issue_diff: Optional[Dict[str, str]]
    body: str


@dataclass # essentially a struct
class Issue:
    retrieved: datetime.datetime # time when the issue was scraped
    id: int
    summary: str # summary = title
    author: str
    author_roles: List[str]
    published: datetime.datetime
    stars: int
    metadata: Dict[str, str]
    labels: List[str]
    description: str # description = main text
    comments: List[Comment]


class ScrapeException(Exception):
    pass # todo: add message asking people to report an issue


IssueWebElement = NewType('IssueWebElement', WebElement)
LeftColumnWebElement = NewType('LeftColumnWebElement', WebElement)
RightColumnWebElement = NewType('RightColumnWebElement', WebElement)
HeaderWebElement = NewType('HeaderWebElement', WebElement)
IssueDetailsWebElement = NewType('IssueDetailsWebElement', WebElement)

class IssueScraper:
    """
    Uses Chrome to web scrape Monorail issues.
    """

    driver: WebDriver

    def __init__(self):
        self.driver = webdriver.Chrome()

    def __del__(self):
        self.driver.close()

    def scrape(self, url: str) -> Issue:
        """
        :param url: The page of the issue report to scrape from
        :return: the scraped Issue
        """
        raise NotImplementedError('todo') # todo implement

    def _get_shadow_root(self, elem: WebElement) -> WebElement:
        # derived from https://www.seleniumeasy.com/selenium-tutorials/accessing-shadow-dom-elements-with-webdriver
        shadow_root = self.driver.execute_script('return arguments[0].shadowRoot', elem)
        return shadow_root

    def _get_issue_elem(self, url: str) -> IssueWebElement:
        """
        :param url: the page of the issue report to scrape from
        :return: the element that contains everything between (and excluding) the top white bar
        (the one w/ the search bar) and the bottom row of links (starting w/ "About Monorail")
        """
        self.driver.get(url)

        mr_app = self.driver.find_element_by_tag_name('mr-app')
        mr_app_shadow = self._get_shadow_root(mr_app)
        main = mr_app_shadow.find_element_by_tag_name('main')
        mr_issue_page = main.find_element_by_tag_name('mr-issue-page')
        mr_issue_page_shadow = self._get_shadow_root(mr_issue_page)

        # sometimes (nondeterministically) the issue element is not ready/otherwise missing
        # current solution is to wait a second before retrying, and try at most 5 times
        # there's probably a more clever solution w/ WebDriverWait, but this works for now
        issue_elem: WebElement
        issue_elem_is_found = False
        num_attempts_to_get_issue_elem = 0
        while not issue_elem_is_found:
            try:
                issue_elem = mr_issue_page_shadow.find_element_by_id('issue')
                issue_elem_is_found = True
            except NoSuchElementException:
                time.sleep(1)
                num_attempts_to_get_issue_elem += 1

                if num_attempts_to_get_issue_elem > 5:
                    ScrapeException('Unable to get the issue element.')

        return IssueWebElement(issue_elem)

    def _get_left_column(self, issue_elem: IssueWebElement) -> LeftColumnWebElement:
        """
        :param issue_elem: output of self._get_issue_elem
        :return: the (shadow) element that contains the left column, which contains stars, metadata, and labels
        """
        metadata_container = issue_elem.find_element_by_class_name('metadata-container')
        mr_issue_metadata = metadata_container.find_element_by_tag_name('mr-issue-metadata')
        mr_issue_metadata_shadow = self._get_shadow_root(mr_issue_metadata)

        return LeftColumnWebElement(mr_issue_metadata_shadow)

    def _get_num_stars(self, left_column: LeftColumnWebElement) -> int:
        """
        :param left_column: output of self._get_left_column
        :return: number of stars
        """
        star_line_elem = left_column.find_element_by_class_name('star-line')
        star_line_text = star_line_elem.text
        num_stars = int(regex_util.capture(star_line_text, r'Starred by ([0-9]+) users?')) # r'users?' matches user or users
        return num_stars

    @staticmethod
    def _get_text_if_possible(web_elem: Optional[WebElement]) -> str:
        """
        :param web_elem: A possibly null WebElement
        :return: Empty string if web_elem is null; web_elem.text otherwise
        """
        if web_elem is None:
            return ''
        else:
            return web_elem.text


    def _get_metadata(self, left_column: LeftColumnWebElement) -> Dict[str, str]:
        """
        :param left_column: output of self._get_left_column
        :return: dict of metadata header -> data (e.g: 'Modified' -> 'Feb 10, 2020')
        """
        mr_metadata = left_column.find_element_by_tag_name('mr-metadata')
        mr_metadata_shadow = self._get_shadow_root(mr_metadata)

        table_rows = mr_metadata_shadow.find_elements_by_tag_name('tr')

        # get rid of cue-availability_msgs
        table_rows = [tr for tr in table_rows if tr.get_attribute('class') != 'cue-availability_msgs']

        table_header_elems: Iterator[Optional[WebElement]] = map(lambda tr: tr.find_element_by_tag_name('th'), table_rows)
        table_data_elems: Iterator[Optional[WebElement]] = map(lambda tr: tr.find_element_by_tag_name('td'), table_rows)

        table_headers: Iterator[str] = map(lambda th: self._get_text_if_possible(th), table_header_elems)
        table_data: Iterator[str] = map(lambda td: self._get_text_if_possible(td), table_data_elems)

        #delete colons from headers
        table_headers = map(lambda header: header.replace(':', ''), table_headers)

        metadata_table = dict(zip(table_headers, table_data))
        return metadata_table

    def _get_labels(self, left_column: LeftColumnWebElement) -> List[str]:
        """
        :param left_column:
        :return:
        """
        labels_container = left_column.find_element_by_class_name('labels-container')
        label_elems = labels_container.find_elements_by_class_name('label')

        labels: Iterator[str] = map(lambda label_elem: label_elem.text, label_elems)
        return list(labels)

    def _get_right_column(self, issue_elem: IssueWebElement) -> RightColumnWebElement:
        container_issue = issue_elem.find_element_by_class_name('container-issue')
        return RightColumnWebElement(container_issue)

    def _get_header(self, right_column: RightColumnWebElement) -> HeaderWebElement:
        issue_header_container = right_column.find_element_by_class_name('issue-header-container')
        mr_issue_header = issue_header_container.find_element_by_tag_name('mr-issue-header')
        mr_issue_header_shadow = self._get_shadow_root(mr_issue_header)
        main_text = mr_issue_header_shadow.find_element_by_class_name('main-text')
        return HeaderWebElement(main_text)

    def _get_id(self, header: HeaderWebElement) -> int:
        header_text = header.text
        return int(capture(header_text, r'Issue ([0-9]+?):'))

    def _get_summary(self, header: HeaderWebElement) -> str:
        header_text = header.text
        return capture(header_text, r'Issue [0-9]+?: (.+?)[\n$]')

    def _get_author(self, header: HeaderWebElement) -> str:
        mr_user_link = header.find_element_by_tag_name('mr-user-link')
        return mr_user_link.text

    def _get_author_roles(self, header: HeaderWebElement) -> List[str]:
        role_label_elems = header.find_elements_by_class_name('role-label')
        role_labels: Iterator[str] = map(lambda elem: elem.text, role_label_elems)
        return list(role_labels)

    def _get_published(self, header: HeaderWebElement) -> str:
        chops_timestamp = header.find_element_by_tag_name('chops-timestamp')
        time_published = chops_timestamp.get_attribute('title')
        return time_published

    def _get_issue_details(self, right_column: RightColumnWebElement) -> IssueDetailsWebElement:
        container_issue_content = right_column.find_element_by_class_name('container-issue-content')
        mr_issue_details = container_issue_content.find_element_by_tag_name('mr-issue-details')
        mr_issue_details_shadow = self._get_shadow_root(mr_issue_details)
        return IssueDetailsWebElement(mr_issue_details_shadow)

    def _get_description(self, issue_details: IssueDetailsWebElement):
        description_elem = issue_details.find_element_by_tag_name('mr-description')
        return description_elem.text

    def _get_comments(self, issue_details: IssueDetailsWebElement) -> List[Comment]:
        mr_comment_list = issue_details.find_element_by_tag_name('mr-comment-list')
        mr_comment_list_shadow = self._get_shadow_root(mr_comment_list)

        mr_comment_elems = mr_comment_list_shadow.find_elements_by_tag_name('mr-comment')
        comments: Iterator[Comment] = map(lambda elem: self._get_comment(elem), mr_comment_elems)
        return list(comments)

    def _get_comment(self, mr_comment: WebElement) -> Comment:
        mr_comment_shadow = self._get_shadow_root(mr_comment)
        comment_header = mr_comment_shadow.find_element_by_class_name('comment-header')
        div_under_comment_header = comment_header.find_element_by_tag_name('div')

        # todo: consider refactoring into 6 smaller subroutines

        # Comment index
        comment_link = div_under_comment_header.find_element_by_class_name('comment-link')
        index = int(capture(comment_link.text, r'Comment ([0-9]+)'))

        # Comment author
        mr_user_link = div_under_comment_header.find_element_by_tag_name('mr-user-link')
        author = mr_user_link.text

        # Comment author roles
        role_label_elems: List[WebElement] = div_under_comment_header.find_elements_by_class_name('role-label')
        role_labels = list(map(lambda elem: elem.text, role_label_elems))

        # Comment published datetime
        chops_timestamp = div_under_comment_header.find_element_by_tag_name('chops-timestamp')
        time_published = chops_timestamp.get_attribute('title')

        # Issue diff
        issue_diff_elem = mr_comment_shadow.find_element_by_class_name('issue-diff')
        issue_diff = issue_diff_elem.text

        # Comment body
        comment_body_elem = mr_comment_shadow.find_element_by_class_name('comment-body')
        comment_body = comment_body_elem.text

        comment = Comment(index=index, author=author, author_roles=role_labels, published=time_published,
                          issue_diff=issue_diff, body=comment_body)
        return comment
