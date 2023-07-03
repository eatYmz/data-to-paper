from dataclasses import dataclass, field
from typing import Optional, Tuple, Type, List, Union

from data_to_paper.base_steps.base_steps_runner import BaseStepsRunner
from data_to_paper.base_steps.request_products_from_user import DirectorProductGPT

from .cast import ScientificAgent
from .add_citations import AddCitationReviewGPT
from .coding_steps import RequestCodeProducts
from .get_template import get_paper_template_path
from .literature_search import WritingLiteratureSearchReviewGPT, GoalLiteratureSearchReviewGPT
from .produce_pdf_step import ProduceScientificPaperPDFWithAppendix
from .scientific_products import ScientificProducts
from .scientific_stage import ScientificStages
from .reviewing_steps import GoalReviewGPT, PlanReviewGPT, \
    ResultsInterpretationReviewGPT, TablesReviewBackgroundProductsConverser, KeyNumericalResultsExtractorReviewGPT, \
    TablesNamesReviewGPT, HypothesesTestingPlanReviewGPT, IsGoalOK, ReGoalReviewGPT
from .writing_steps import SectionWriterReviewBackgroundProductsConverser, \
    FirstTitleAbstractSectionWriterReviewGPT, SecondTitleAbstractSectionWriterReviewGPT, \
    MethodsSectionWriterReviewGPT, IntroductionSectionWriterReviewGPT, ReferringTablesSectionWriterReviewGPT, \
    DiscussionSectionWriterReviewGPT


PAPER_TEMPLATE_FILE: str = get_paper_template_path('standard_paper.tex')
SECTIONS_TO_ADD_CITATIONS_TO = ['introduction', 'discussion']
SECTIONS_TO_ADD_TABLES_TO = ['results']


@dataclass
class ScientificStepsRunner(BaseStepsRunner):

    cast = ScientificAgent
    products: ScientificProducts = field(default_factory=ScientificProducts)
    research_goal: Optional[str] = None
    max_goal_refinement_iterations: int = 3

    should_do_data_exploration: bool = True
    should_do_data_preprocessing: bool = False
    should_prepare_data_analysis_plan: bool = False
    should_prepare_hypothesis_testing_plan: bool = True
    should_do_literature_search: bool = True
    should_add_citations: bool = False
    should_add_tables: bool = True
    should_interpret_results: bool = False

    def get_sections_to_writing_class(
            self) -> List[Tuple[Union[str, Tuple[str, ...]], Type[SectionWriterReviewBackgroundProductsConverser]]]:
        return [
            (('results',), (ReferringTablesSectionWriterReviewGPT if self.should_add_tables
                            else SectionWriterReviewBackgroundProductsConverser)),
            (('title', 'abstract'), SecondTitleAbstractSectionWriterReviewGPT),
            (('methods',), MethodsSectionWriterReviewGPT),
            (('introduction',), IntroductionSectionWriterReviewGPT),
            (('discussion',), DiscussionSectionWriterReviewGPT),
            #  (('conclusion',), ConclusionSectionWriterReviewGPT),
        ]

    def assert_paper_sections_to_write_matches_template(self, template_sections, sections_to_writing_class):
        flattened_paper_sections_to_write = []
        for sections, _ in sections_to_writing_class:
            if not isinstance(sections, str):
                flattened_paper_sections_to_write.extend(sections)
        assert set(flattened_paper_sections_to_write) == set(template_sections)

    def _run_all_steps(self) -> ScientificProducts:

        products = self.products  # Start with empty products

        # Get the paper section names:
        paper_producer = ProduceScientificPaperPDFWithAppendix.from_(
            self,
            paper_template_filepath=PAPER_TEMPLATE_FILE,
            output_filename='paper.pdf',
        )
        paper_section_names = paper_producer.get_paper_section_names()
        sections_and_writing_class = self.get_sections_to_writing_class()
        self.assert_paper_sections_to_write_matches_template(paper_section_names, sections_and_writing_class)

        # Data file descriptions:
        director_converser = DirectorProductGPT.from_(self,
                                                      assistant_agent=ScientificAgent.Director,
                                                      user_agent=ScientificAgent.Performer,
                                                      conversation_name='with_director',
                                                      )
        self.advance_stage_and_set_active_conversation(ScientificStages.DATA, ScientificAgent.Director)
        products.data_file_descriptions = director_converser.get_product_or_no_product_from_director(
            product_field='data_file_descriptions', returned_product=self.data_file_descriptions)
        self.send_product_to_client('data_file_descriptions')

        # Data exploration
        if self.should_do_data_exploration:
            self.advance_stage_and_set_active_conversation(ScientificStages.EXPLORATION, ScientificAgent.DataExplorer)
            RequestCodeProducts.from_(self, code_step='data_exploration').get_code_and_output_and_descriptions()
            self.send_product_to_client('codes_and_outputs:data_exploration')

        # Goal
        self.advance_stage_and_set_active_conversation(ScientificStages.GOAL, ScientificAgent.Director)
        products.research_goal = director_converser.get_product_or_no_product_from_director(
            product_field='research_goal', returned_product=self.research_goal,
            acknowledge_no_product_message="OK. no problem. I will devise the goal myself.")
        is_auto_goal = products.research_goal is None
        if is_auto_goal:
            # we did not get a goal from the director, so we need to devise it ourselves:
            self.set_active_conversation(ScientificAgent.GoalReviewer)
            products.research_goal = GoalReviewGPT.from_(self).run_dialog_and_get_valid_result()
        # self.send_product_to_client('research_goal')

        goal_refinement_iteration = 0
        while True:
            # Literature search
            if self.should_do_literature_search:
                # TODO: need a dedicated client Stage for literature search
                self.set_active_conversation(ScientificAgent.CitationExpert)
                products.literature_search['goal'] = GoalLiteratureSearchReviewGPT.from_(self).get_literature_search()
                # self.send_product_to_client('citations')

            # Check if the goal is OK
            if not is_auto_goal or goal_refinement_iteration == self.max_goal_refinement_iterations or \
                    IsGoalOK.from_(self).is_goal_ok():
                break

            # Goal is not OK, so we need to devise the goal according to the literature search:
            goal_refinement_iteration += 1
            products.research_goal = ReGoalReviewGPT.from_(self).run_dialog_and_get_valid_result()
        # TODO: need to decide what and how to send to the client, we need to somehow split between
        #  stages and produces
        self.send_product_to_client('research_goal')

        # Plan
        self.advance_stage_and_set_active_conversation(ScientificStages.PLAN, ScientificAgent.PlanReviewer)
        # Analysis plan
        if self.should_prepare_data_analysis_plan:
            products.analysis_plan = PlanReviewGPT.from_(self).run_dialog_and_get_valid_result()
            # self.send_product_to_client('analysis_plan')

        # Hypotheses testing plan
        if self.should_prepare_hypothesis_testing_plan:
            products.hypothesis_testing_plan = \
                HypothesesTestingPlanReviewGPT.from_(self).run_dialog_and_get_valid_result()
            # self.send_product_to_client('hypothesis_testing_plan')

        if not self.should_prepare_data_analysis_plan and not self.should_prepare_hypothesis_testing_plan:
            raise ValueError("At least one of the following should be True: "
                             "should_prepare_data_analysis_plan, should_prepare_hypothesis_testing_plan")
        # TODO: currently sending hypothesis testing plan to the client, need to decide what we really want to send
        self.send_product_to_client('hypothesis_testing_plan')

        # Data Preprocessing
        if self.should_do_data_preprocessing:
            self.advance_stage_and_set_active_conversation(
                ScientificStages.PREPROCESSING, ScientificAgent.DataPreprocessor)
            RequestCodeProducts.from_(self, code_step='data_preprocessing') \
                .get_code_and_output_and_descriptions(with_file_descriptions=False)
            self.send_product_to_client('codes_and_outputs:data_preprocessing')

        # Tables names
        if self.should_add_tables:
            products.tables_names = TablesNamesReviewGPT.from_(self).run_dialog_and_get_valid_result()

        # Analysis code and output
        self.advance_stage_and_set_active_conversation(ScientificStages.CODE, ScientificAgent.Debugger)
        RequestCodeProducts.from_(self, code_step='data_analysis').get_code_and_output_and_descriptions()
        self.send_product_to_client('codes_and_outputs:data_analysis')

        self.advance_stage_and_set_active_conversation(ScientificStages.INTERPRETATION,
                                                       ScientificAgent.InterpretationReviewer)

        # Tables
        if self.should_add_tables:
            products.tables['results'] = []
            for table_num, table_name in products.tables_names.items():
                table = TablesReviewBackgroundProductsConverser.from_(
                    self, section_names=['table'], table_name=table_name, conversation_name=table_num,
                ).run_dialog_and_get_valid_result()[0]
                products.tables['results'].append(table)

        # Numerical results
        products.numeric_values = KeyNumericalResultsExtractorReviewGPT.from_(self).run_dialog_and_get_valid_result()
        self.send_product_to_client('tables_and_numeric_values')

        # Results interpretation
        if self.should_interpret_results:
            self.advance_stage_and_set_active_conversation(
                ScientificStages.INTERPRETATION, ScientificAgent.InterpretationReviewer)
            products.results_summary = ResultsInterpretationReviewGPT.from_(self).get_value()
            self.send_product_to_client('results_summary')

        # literature review and scope
        self.advance_stage_and_set_active_conversation(ScientificStages.LITERATURE_REVIEW_AND_SCOPE,
                                                       ScientificAgent.Writer)
        products.paper_sections_and_optional_citations['title'], \
            products.paper_sections_and_optional_citations['abstract'] = \
            FirstTitleAbstractSectionWriterReviewGPT.from_(self, section_names=['title', 'abstract']
                                                           ).write_sections_with_citations()
        products.literature_search['writing'] = WritingLiteratureSearchReviewGPT.from_(self).get_literature_search()
        # TODO: create the actual scope and literature review scientific product (currently it is just "hello")
        self.send_product_to_client('scope_and_literature_search')

        # Paper sections
        self.advance_stage_and_set_active_conversation(ScientificStages.WRITING, ScientificAgent.Writer)
        for section_names, writing_class in sections_and_writing_class:
            # writing section
            sections_with_citations = \
                writing_class.from_(self, section_names=section_names).write_sections_with_citations()
            for section_name, section_and_citations in zip(section_names, sections_with_citations):
                products.paper_sections_and_optional_citations[section_name] = section_and_citations
        self.send_product_to_client('most_updated_paper')

        # Add citations to relevant paper sections
        if self.should_add_citations:
            self.advance_stage_and_set_active_conversation(ScientificStages.CITATIONS, ScientificAgent.CitationExpert)
            for section_name in SECTIONS_TO_ADD_CITATIONS_TO:
                products.paper_sections_and_optional_citations[section_name] = \
                    AddCitationReviewGPT.from_(self, section_name=section_name,
                                               conversation_name=f'add_citations_to_{section_name}') \
                        .rewrite_section_with_citations()
            self.send_product_to_client('most_updated_paper')

        paper_producer.assemble_compile_paper()

        return products
