from dataclasses import dataclass
from typing import Optional

from scientistgpt.cast import Agent
from scientistgpt.conversation.message_designation import RangeMessageDesignation
from scientistgpt.env import SUPPORTED_PACKAGES
from scientistgpt.gpt_interactors.debugger_gpt import DebuggerGPT
from scientistgpt.gpt_interactors.types import CoderProductHolder
from scientistgpt.run_gpt_code.code_runner import CodeAndOutput
from scientistgpt.utils import dedent_triple_quote_str, is_code_in_response

from .goal_and_plan import BaseScientificGPT


MAX_CODE_REVISIONS = 3
MAX_CODE_WRITING_ATTEMPTS = 3
MAX_DEBUG_ITERATIONS_PER_ATTEMPT = 12
MAX_REGENERATING_MULTI_CHOICE_RESPONSE = 3

@dataclass
class CodeFeedbackGPT(BaseScientificGPT, CoderProductHolder):
    background_product_fields = ['data_file_descriptions', 'research_goal', 'analysis_plan']
    conversation_name: str = 'code_debugging'
    assistant_agent: Agent = Agent.Debugger
    user_agent: Agent = Agent.Student

    def get_analysis_code(self) -> Optional[CodeAndOutput]:
        self.initialize_conversation_if_needed()
        self._pre_populate_background()
        for revision in range(MAX_CODE_REVISIONS):
            code_and_output = self._run_debugger()
            if code_and_output is None:
                return None

            gpt_choice = self._ask_chatgpt_whether_further_code_revisions_are_needed(code_and_output)
            if gpt_choice == 1:
                return code_and_output
            self.apply_append_user_message(dedent_triple_quote_str("""
                Please re-write the code to fix the problem.
                """), tag='code_revision')

    def _ask_for_code(self, revision: int):
        user_prompt = dedent_triple_quote_str("""
            Write a complete short Python code to perform the data analysis plan.
            If needed, you can use the following packages in your code: {}.
            The output of your code should be a text file named "{}".
            Do not plot anything to screen or other files.

            If the code has some key parameter values, like certain thresholds,
            put these parameters in a dedicated variable and add a comment, like this:
            `some_important_parameter = 123.4  # <-- we might want to change this value later`
            """).format(SUPPORTED_PACKAGES, self.output_filename)
        self.apply_append_user_message(user_prompt, tag='request_code')

    def _pre_populate_background(self):
        super()._pre_populate_background()
        self._ask_for_code(revision=0)

    def _run_debugger(self) -> Optional[CodeAndOutput]:
        start_tag = 'start_debug'
        for attempt in range(MAX_CODE_WRITING_ATTEMPTS):
            # in each attempt, we are resetting the conversation back to this tag:
            attempt_str = f"(attempt {attempt + 1}/{MAX_CODE_WRITING_ATTEMPTS})"
            self.comment(f'Transfer to DebuggerGPT {attempt_str}.', tag=start_tag)

            # we now call the debugger that will try to run and provide feedback in multiple iterations:
            code_and_output = DebuggerGPT(
                conversation_name=self.conversation_name,
                user_agent=self.user_agent,
                assistant_agent=self.assistant_agent,
                output_filename=self.output_filename,
                data_files=self.data_filenames,
                max_debug_iterations=MAX_DEBUG_ITERATIONS_PER_ATTEMPT,
                gpt_script_filename=f"{self.gpt_script_filename}_attempt{attempt}",
            ).run_debugging()
            if code_and_output is None:
                # debugging failed
                self.comment(f'Debugging failed {attempt_str}.')
                continue

            # debugging succeeded. we now forge the conversation as if chatgpt immediately sent the correct code:
            self.conversation_manager.delete_messages(
                message_designation=RangeMessageDesignation.from_(start=start_tag, end=-1),
                comment='Deleting all debugging correspondence.')
            assert self.conversation[-1].tag == 'request_code'

            self.apply_append_surrogate_message(
                content=dedent_triple_quote_str("""
                Here is the code to perform the analysis. It saves results to the file "{}".
                ```python
                {}
                ```
                """).format(self.output_filename, code_and_output.code),
                comment='Adding the debugged code as if it was the original response.',
                is_code=True,
            )
            return code_and_output
        return None

    def _ask_for_code_explanation(self):
        code_and_output.explanation = self.apply_append_user_message(
            content=dedent_triple_quote_str("""
            Please explain what your code does. Do not provide a line-by-line explanation, rather provide a \
            high-level explanation of the code in a language suitable for a Methods section of a research \
            paper.

            Also explain what does the code writes into the {} file, and how we would be the scientific \
            implications of the results written into that file.
            """).format(self.output_filename),
        )
        code_and_output.explanation = self.apply_get_and_append_assistant_message()

    def _ask_chatgpt_whether_further_code_revisions_are_needed(self, code_and_output: CodeAndOutput) -> Optional[int]:
        user_prompt = dedent_triple_quote_str("""
            I ran your code. Here is the content of the output file ({}):
            ```
            {}
            ```

            Please choose one of the following options:

            a. The results seem reasonable. Let's proceed.

            b. Something is wrong. I need to go back and change the code.

            Answer with just the letter designating the option you choose \
            (only type a single character: "a", or "b").
            """).format(
            self.output_filename,
            code_and_output.output,
        )
        self.apply_append_user_message(content=user_prompt, tag='output_file_content')

        response = self.apply_get_and_append_assistant_message()
        for num_tries in range(MAX_REGENERATING_MULTI_CHOICE_RESPONSE):
            if 'a' in response and 'b' not in response and len(response) < 5:
                self.comment('ScientistGPT declared it is satisfied with the analysis.')
                return 1
            elif 'b' in response and 'a' not in response and len(response) < 5:
                self.comment(f'ScientistGPT declared it needs to revise the code. Starting a new revision.'
                             f'({self.number_of_successful_code_revisions + 1}/{MAX_CODE_REVISIONS}).')
                return 2
            elif is_code_in_response(response):
                # the scientist sent code, so we assume it wants to change the code (choosing "2")
                response = self.conversation_manager.replace_last_response(
                    content='b',
                    comment='ChatGPT sent code instead of "a"/"b". We assume it wants to change the code ("b").')
            else:
                if num_tries < MAX_REGENERATING_MULTI_CHOICE_RESPONSE - 1:
                    response = self.conversation_manager.regenerate_previous_response(
                        comment='ScientistGPT did not choose a valid option. Regenerating response.')
        return None
